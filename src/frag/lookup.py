"""Resolve, validate, execute, and replay filing-scoped revenue lookups."""

import json
import re
from collections.abc import Callable
from time import perf_counter
from typing import Any, Literal, TypedDict

from frag.citations import revenue_cell_citation
from frag.local_model import MODEL_ALIAS, MODEL_SETTINGS, InvalidModelResponse, ModelUnavailable
from frag.store import SourceError

Planner = Callable[[dict[str, Any]], str]
METRIC = "reported_consolidated_revenue"
RECORD_VERSION = 1
REVENUE = r"(?:(?:annual|reported|consolidated|total) )*revenue"
YEAR = r"(?:fy ?|fiscal year )?([1-9][0-9]{3})"
LOOKUP = re.compile(
    rf"(?:(?:what (?:was|is)|show me|look up) (?:the )?)?"
    rf"(?:{REVENUE} (?:in |for )?{YEAR}|{YEAR} {REVENUE})[?.]?"
)
CLARIFICATION = "Ask for annual reported consolidated revenue for one fiscal year, such as “What was revenue in FY2023?”"


class ResolvedLookup(TypedDict):
    operation: Literal["lookup"]
    metric: str
    fiscal_year: int


def _resolve_request(question: str) -> ResolvedLookup | None:
    if len(question) > 300:
        return None
    match = LOOKUP.fullmatch(" ".join(question.lower().split()))
    if match is None:
        return None
    return {"operation": "lookup", "metric": METRIC, "fiscal_year": int(match[1] or match[2])}


def _eligible_facts(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        fact for fact in source.get("facts", [])
        if fact["source_id"] == source["source_id"]
        and fact["metric"] == METRIC
        and fact["reporting_period"]["kind"] == "annual"
        and fact["status"] == "verified"
        and fact["normalized_amount"] is not None
        and fact["currency"]
        and fact["scale"]
        and fact["locators"].get("value")
    ]


def _facts_for_year(facts: list[dict[str, Any]], year: int) -> list[dict[str, Any]]:
    return [fact for fact in facts if fact["reporting_period"]["fiscal_year"] == year]


def lookup_citation(source: dict[str, Any], year: int, citation_id: str) -> dict[str, Any] | None:
    facts = _facts_for_year(_eligible_facts(source), year)
    return revenue_cell_citation(facts[0], "revenue") if len(facts) == 1 and citation_id == "revenue" else None


def _evidence(facts: list[dict[str, Any]], year: int) -> list[dict[str, Any]]:
    keys = ("fact_id", "metric", "reporting_period", "normalized_amount", "currency", "scale")
    # Put matching evidence next to the question at the end of the prompt.
    ranked = sorted(facts, key=lambda fact: fact["reporting_period"]["fiscal_year"] == year)
    return [{key: fact[key] for key in keys} for fact in ranked]


def _payload(year: int, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    reference: dict[str, Any] = {"type": "string"}
    if evidence:
        reference["enum"] = [item["fact_id"] for item in evidence]
    return {
        "model": MODEL_ALIAS,
        "temperature": 0,
        "seed": 42,
        "max_tokens": 120,
        "cache_prompt": False,
        "messages": [
            {"role": "system", "content": (
                "Plan a reported consolidated revenue lookup. Find the evidence whose "
                "reporting_period.fiscal_year equals requested_fiscal_year. Copy its exact "
                'fact_id into a JSON object of the form {"operation":"lookup","fact_id":"<ID>"}.'
            )},
            {"role": "user", "content": json.dumps({"evidence": evidence, "requested_fiscal_year": year})},
        ],
        "response_format": {"type": "json_object", "schema": {
            "type": "object",
            "properties": {"operation": {"const": "lookup"}, "fact_id": reference},
            "required": ["operation", "fact_id"],
            "additionalProperties": False,
        }},
    }


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate plan key")
    return result


def _execute(facts: list[dict[str, Any]], year: int, proposal: str) -> dict[str, Any]:
    try:
        plan = json.loads(proposal, object_pairs_hook=_unique_keys) if len(proposal) <= 4096 else None
    except (ValueError, RecursionError):
        plan = None
    invalid = {"status": "invalid_plan", "message": f"The plan did not match the verified FY{year} lookup."}
    if (not isinstance(plan, dict) or set(plan) != {"operation", "fact_id"}
            or plan["operation"] != "lookup" or not isinstance(plan["fact_id"], str)):
        return invalid
    expected = _facts_for_year(facts, year)
    if len(expected) != 1:
        return {
            "status": "evidence_unavailable",
            "message": f"The selected filing does not have one eligible verified revenue fact for FY{year}.",
        }
    fact = expected[0]
    if plan["fact_id"] != fact["fact_id"]:
        return invalid
    return {
        "status": "answered",
        "fiscal_year": year,
        "fact": fact,
        "citations": [revenue_cell_citation(fact, "revenue")],
        "trace": [{
            "operation": "lookup",
            "fact_id": fact["fact_id"],
            "normalized_amount": fact["normalized_amount"],
            "currency": fact["currency"],
        }],
    }


def _identity(source: dict[str, Any]) -> dict[str, Any]:
    return {key: source.get(key) for key in ("source_id", "source_hash", "parser_version", "evidence_version")}


def ask_revenue(
    source: dict[str, Any], question: str, planner: Planner, *, record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    start = perf_counter()
    request = _resolve_request(question)
    if request is None:
        if record is not None:
            raise SourceError("Validation runs require a supported annual revenue lookup question.")
        return {"status": "clarify", "message": CLARIFICATION}

    year = request["fiscal_year"]
    facts = _eligible_facts(source)
    evidence = _evidence(facts, year)
    payload = _payload(year, evidence)
    model_start = perf_counter()
    proposal = None
    execution_start = None
    try:
        proposal = planner(payload)
    except ModelUnavailable:
        outcome = {"status": "model_unavailable", "message": "Start the local planner and try again."}
    except TimeoutError:
        outcome = {"status": "model_timeout", "message": "The local planner timed out."}
    except InvalidModelResponse:
        outcome = {"status": "invalid_plan", "message": "The local planner returned an invalid response."}
    else:
        execution_start = perf_counter()
        outcome = _execute(facts, year, proposal)
    end = perf_counter()
    result = {**_identity(source), **outcome}
    if record is not None:
        record.update({
            "version": RECORD_VERSION,
            "question": question,
            "resolved_request": request,
            "source": _identity(source),
            "evidence": evidence,
            "model_settings": {"expected_server_configuration": MODEL_SETTINGS},
            "model_request": payload,
            "proposed_plan": proposal,
            "validation_status": outcome["status"],
            "result": result,
            "timings_ms": {
                "model": round(((execution_start if execution_start is not None else end) - model_start) * 1000, 3),
                "validation_and_execution": round((end - execution_start) * 1000, 3)
                if execution_start is not None else None,
                "total": round((end - start) * 1000, 3),
            },
        })
    return result


def replay_lookup(source: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    question, proposal = record.get("question"), record.get("proposed_plan")
    if record.get("version") != RECORD_VERSION or not isinstance(question, str) or not isinstance(proposal, str):
        raise SourceError("The validation record must contain a supported saved proposal.")
    request = _resolve_request(question)
    if request is None or record.get("resolved_request") != request:
        raise SourceError("The saved request does not match its question.")
    year = request["fiscal_year"]
    facts = _eligible_facts(source)
    evidence = _evidence(facts, year)
    identity = _identity(source)
    if (record.get("source") != identity or record.get("evidence") != evidence
            or record.get("model_request") != _payload(year, evidence)):
        raise SourceError("The saved source or evidence does not match the current filing evidence.")
    return {**identity, **_execute(facts, year, proposal)}
