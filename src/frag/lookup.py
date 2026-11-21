"""Resolve, validate, execute, and replay filing-scoped revenue questions."""

import json
import re
from collections.abc import Callable
from time import perf_counter
from typing import Any, Literal, TypedDict

from frag.citations import has_citable_amount, revenue_cell_citation
from frag.growth import calculate_growth
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
GROWTH_PHRASE = rf"(?:(?:what (?:was|is)|show me) (?:the )?)?{REVENUE} growth"
GROWTH_FROM = re.compile(
    rf"(?:how did {REVENUE} change|{GROWTH_PHRASE}) from {YEAR} to {YEAR}[?.]?"
)
GROWTH_BETWEEN = re.compile(rf"{GROWTH_PHRASE} between {YEAR} and {YEAR}[?.]?")
CLARIFICATION = (
    "Ask for annual reported consolidated revenue for one fiscal year, such as “What was revenue in FY2023?” "
    "For growth, name both fiscal years in order, such as “How did revenue change from FY2022 to FY2023?”"
)
GENERATION_SETTINGS = {"model": MODEL_ALIAS, "temperature": 0, "seed": 42, "cache_prompt": False}
GROWTH_STEPS = (("subtract", 2), ("divide", 2), ("to_percent", 1))


class ResolvedLookup(TypedDict):
    operation: Literal["lookup"]
    metric: str
    fiscal_year: int


class ResolvedGrowth(TypedDict):
    operation: Literal["growth"]
    metric: str
    prior_year: int
    current_year: int


ResolvedRequest = ResolvedLookup | ResolvedGrowth


def resolve_request(question: str) -> ResolvedRequest | None:
    if len(question) > 300:
        return None
    normalized = " ".join(question.lower().split())
    match = LOOKUP.fullmatch(normalized)
    if match is not None:
        return {"operation": "lookup", "metric": METRIC, "fiscal_year": int(match[1] or match[2])}
    match = GROWTH_FROM.fullmatch(normalized) or GROWTH_BETWEEN.fullmatch(normalized)
    if not match:
        return None
    prior, current = map(int, match.groups())
    if prior >= current:
        return None
    return {"operation": "growth", "metric": METRIC, "prior_year": prior, "current_year": current}


def _eligible_facts(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        fact for fact in source.get("facts", [])
        if fact["source_id"] == source["source_id"]
        and fact["metric"] == METRIC
        and fact["reporting_period"]["kind"] == "annual"
        and fact["status"] == "verified"
        and has_citable_amount(fact)
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


def _lookup_payload(year: int, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    reference: dict[str, Any] = {"type": "string"}
    if evidence:
        reference["enum"] = [item["fact_id"] for item in evidence]
    return {
        **GENERATION_SETTINGS,
        "max_tokens": 120,
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


def _growth_payload(request: ResolvedGrowth, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    references = [fact["fact_id"] for fact in evidence] + ["subtract", "divide"]
    return {
        **GENERATION_SETTINGS,
        "max_tokens": 320,
        "messages": [
            {"role": "system", "content": (
                "Plan reported consolidated revenue growth. Match each requested fiscal year to "
                "reporting_period.fiscal_year in the evidence. Replace CURRENT and PRIOR with the "
                "corresponding exact fact_id strings. Copy the second input of subtract again as "
                "the second input of divide. The denominator must be the older fiscal year's fact ID. "
                'Use compact JSON with this exact structure: {"operation":"growth","steps":['
                '{"operation":"subtract","inputs":["CURRENT","PRIOR"]},'
                '{"operation":"divide","inputs":["subtract","PRIOR"]},'
                '{"operation":"to_percent","inputs":["divide"]}]}.'
            )},
            {"role": "user", "content": json.dumps({
                "evidence": evidence, "prior_fiscal_year": request["prior_year"],
                "current_fiscal_year": request["current_year"],
            })},
        ],
        "response_format": {"type": "json_object", "schema": {
            "type": "object",
            "properties": {
                "operation": {"const": "growth"},
                "steps": {"type": "array", "minItems": len(GROWTH_STEPS), "maxItems": len(GROWTH_STEPS), "items": {
                    "type": "object",
                    "properties": {
                        "operation": {"enum": [operation for operation, _ in GROWTH_STEPS]},
                        "inputs": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"enum": references}},
                    },
                    "required": ["operation", "inputs"],
                    "additionalProperties": False,
                }},
            },
            "required": ["operation", "steps"],
            "additionalProperties": False,
        }},
    }


def _planner_input(
    facts: list[dict[str, Any]], request: ResolvedRequest,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if request["operation"] == "lookup":
        year = request["fiscal_year"]
        evidence = _evidence(facts, year)
        return evidence, _lookup_payload(year, evidence)
    evidence = _evidence(facts, request["current_year"])
    return evidence, _growth_payload(request, evidence)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate plan key")
    return result


def _parse_plan(proposal: str) -> Any:
    try:
        return json.loads(proposal, object_pairs_hook=_unique_keys) if len(proposal) <= 4096 else None
    except (ValueError, RecursionError):
        return None


def _execute_lookup(facts: list[dict[str, Any]], year: int, plan: Any) -> dict[str, Any]:
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


def _execute_growth(
    source: dict[str, Any], facts: list[dict[str, Any]], request: ResolvedGrowth, plan: Any,
) -> dict[str, Any]:
    invalid = {"status": "invalid_plan", "message": "The plan did not match the requested revenue growth calculation."}
    if not isinstance(plan, dict) or set(plan) != {"operation", "steps"} or plan["operation"] != "growth":
        return invalid
    steps = plan["steps"]
    if not isinstance(steps, list) or len(steps) != len(GROWTH_STEPS):
        return invalid
    for step, (operation, arity) in zip(steps, GROWTH_STEPS, strict=True):
        if (not isinstance(step, dict) or set(step) != {"operation", "inputs"} or step["operation"] != operation
                or not isinstance(step["inputs"], list) or len(step["inputs"]) != arity
                or any(not isinstance(reference, str) for reference in step["inputs"])):
            return invalid

    prior_year, current_year = request["prior_year"], request["current_year"]
    prior, current = _facts_for_year(facts, prior_year), _facts_for_year(facts, current_year)
    if len(prior) != 1 or len(current) != 1:
        return {
            "status": "evidence_unavailable",
            "message": f"Growth requires one eligible verified revenue fact for each of FY{prior_year} and FY{current_year}.",
        }

    # Bind references to resolved roles before the calculator verifies and uses the pair.
    prior_id, current_id = prior[0]["fact_id"], current[0]["fact_id"]
    if [step["inputs"] for step in steps] != [[current_id, prior_id], ["subtract", prior_id], ["divide"]]:
        return invalid
    return {"operation": "growth", **calculate_growth(source, prior_year, current_year)}


def _execute(
    source: dict[str, Any], facts: list[dict[str, Any]], request: ResolvedRequest, proposal: str,
) -> dict[str, Any]:
    plan = _parse_plan(proposal)
    if request["operation"] == "lookup":
        return _execute_lookup(facts, request["fiscal_year"], plan)
    return _execute_growth(source, facts, request, plan)


def _identity(source: dict[str, Any]) -> dict[str, Any]:
    return {key: source.get(key) for key in ("source_id", "source_hash", "parser_version", "evidence_version")}


def ask_revenue(
    source: dict[str, Any], question: str, planner: Planner, *, record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    start = perf_counter()
    request = resolve_request(question)
    if request is None:
        if record is not None:
            raise SourceError("Validation runs require a supported annual revenue lookup or growth question.")
        return {"status": "clarify", "message": CLARIFICATION}

    facts = _eligible_facts(source)
    evidence, payload = _planner_input(facts, request)
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
        outcome = _execute(source, facts, request, proposal)
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


def replay_revenue(source: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    question, proposal = record.get("question"), record.get("proposed_plan")
    if record.get("version") != RECORD_VERSION or not isinstance(question, str) or not isinstance(proposal, str):
        raise SourceError("The validation record must contain a supported saved proposal.")
    request = resolve_request(question)
    if request is None or record.get("resolved_request") != request:
        raise SourceError("The saved request does not match its question.")
    facts = _eligible_facts(source)
    evidence, expected_payload = _planner_input(facts, request)
    identity = _identity(source)
    saved_payload = record.get("model_request")
    if not isinstance(saved_payload, dict) or not isinstance(saved_payload.get("model"), str):
        raise SourceError("The validation record must contain its original model request.")
    # The alias identifies the original planner. Replay validates the proposal with no model loaded.
    expected_payload["model"] = saved_payload["model"]
    if (record.get("source") != identity or record.get("evidence") != evidence
            or saved_payload != expected_payload):
        raise SourceError("The saved source or evidence does not match the current filing evidence.")
    return {**identity, **_execute(source, facts, request, proposal)}


replay_lookup = replay_revenue
