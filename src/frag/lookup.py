"""Resolve, validate, execute, and replay filing-scoped revenue questions."""

import json
import re
from collections.abc import Callable
from time import perf_counter
from typing import Any, Literal, NotRequired, TypedDict

from frag import dated_revenue
from frag.citations import has_citable_amount, revenue_cell_citation, statement_period_citation
from frag.growth import METRIC as METRIC
from frag.growth import annual_revenue_facts, assess_growth, calculate_growth, disclosure_citations, observation_gap
from frag.local_model import MODEL_ALIAS, MODEL_SETTINGS, InvalidModelResponse, ModelUnavailable
from frag.revenue import PARSER_VERSION as LEGACY_STATEMENT_PARSER
from frag.store import SourceError

Planner = Callable[[dict[str, Any]], str]
RECORD_VERSION = 1
DATED_GROWTH_RECORD_VERSION = 2
STATEMENT_LOOKUP_RECORD_VERSION = 3
ORIGINAL_GROWTH_RECORD_VERSION = 4
EVIDENCE_GAP_RECORD_VERSION = 5
REVENUE = r"(?:(?:annual|reported|consolidated|total) )*revenue"
YEAR = r"(?:fy ?|fiscal year )?([1-9][0-9]{3})"
LOOKUP = re.compile(
    rf"(?:(?:what (?:was|is)|show me|look up) (?:the )?)?"
    rf"(?:{REVENUE} (?:in |for )?{YEAR}|{YEAR} {REVENUE})[?.]?"
)
GROWTH_PHRASE = rf"(?:(?:what (?:was|is)|show me) (?:the )?)?{REVENUE} growth"
EQUAL_LENGTH = r"( using equal-length fiscal years)?[?.]?"
GROWTH_FROM = re.compile(
    rf"(?:how did {REVENUE} change|{GROWTH_PHRASE}) from {YEAR} to {YEAR}{EQUAL_LENGTH}"
)
GROWTH_BETWEEN = re.compile(rf"{GROWTH_PHRASE} between {YEAR} and {YEAR}{EQUAL_LENGTH}")
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
    equal_length: NotRequired[bool]


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
    prior, current = int(match[1]), int(match[2])
    if prior >= current:
        return None
    growth: ResolvedGrowth = {"operation": "growth", "metric": METRIC, "prior_year": prior, "current_year": current}
    if match[3]:
        growth["equal_length"] = True
    return growth


def _eligible_facts(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        fact for fact in annual_revenue_facts(source)
        if fact["status"] == "verified" and has_citable_amount(fact)
    ]


def _facts_for_year(facts: list[dict[str, Any]], year: int) -> list[dict[str, Any]]:
    return [fact for fact in facts if fact["reporting_period"]["fiscal_year"] == year]


def lookup_citation(source: dict[str, Any], year: int, citation_id: str) -> dict[str, Any] | None:
    eligible = _eligible_facts(source)
    if citation_id == "statement-periods":
        gap = _lookup_gap(source, eligible, year)
        return gap["citations"][0] if gap and gap["reason"] == "absent" else None
    facts = _facts_for_year(eligible, year)
    if len(facts) != 1:
        return None
    return next((item for item in _lookup_citations(facts[0]) if item["id"] == citation_id), None)


def _lookup_citations(fact: dict[str, Any], *, legacy: bool = False) -> list[dict[str, Any]]:
    include_context = fact["parser_version"] == LEGACY_STATEMENT_PARSER and not legacy
    citations = [revenue_cell_citation(fact, "revenue", include_statement_context=include_context)]
    if include_context or fact["parser_version"] in dated_revenue.FILING_SCOPED_PARSERS:
        citations.extend(disclosure_citations([fact], {}).values())
    return citations


def _evidence(facts: list[dict[str, Any]], year: int) -> list[dict[str, Any]]:
    keys = ("fact_id", "metric", "reporting_period", "normalized_amount", "currency", "scale")
    # Put matching evidence next to the question at the end of the prompt.
    ranked = sorted(facts, key=lambda fact: fact["reporting_period"]["fiscal_year"] == year)
    evidence = [{key: fact[key] for key in keys} for fact in ranked]
    for fact, item in zip(ranked, evidence, strict=True):
        if fact.get("parser_version") in dated_revenue.FILING_SCOPED_PARSERS:
            # Keep the request identical for newly extracted and cached observations.
            item["reporting_period"] = dict(sorted(item["reporting_period"].items()))
    return evidence


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
    source: dict[str, Any], facts: list[dict[str, Any]], request: ResolvedRequest, *, legacy_growth: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if request["operation"] == "lookup":
        year = request["fiscal_year"]
        if source.get("parser_version") in dated_revenue.FILING_SCOPED_PARSERS:
            facts = _facts_for_year(facts, year)
        evidence = _evidence(facts, year)
        return evidence, _lookup_payload(year, evidence)
    if source.get("parser_version") in dated_revenue.FILING_SCOPED_PARSERS and not legacy_growth:
        prior, current = request["prior_year"], request["current_year"]
        pair = [fact for fact in facts if fact["reporting_period"]["fiscal_year"] in (prior, current)]
        # Present the reviewed operands in subtraction order.
        evidence = _evidence(pair, prior)
        for item in evidence:
            item["role"] = "current" if item["reporting_period"]["fiscal_year"] == current else "prior"
        payload = _growth_payload(request, evidence)
        if [item["role"] for item in evidence] == ["current", "prior"]:
            current_id, prior_id = (item["fact_id"] for item in evidence)
            plan = {"operation": "growth", "steps": [
                {"operation": operation, "inputs": inputs}
                for (operation, _), inputs in zip(GROWTH_STEPS, _growth_inputs(current_id, prior_id), strict=True)
            ]}
            payload["messages"][1]["content"] += "\nUse these exact inputs in the growth plan: " + json.dumps(plan)
        return evidence, payload
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


def _execute_lookup(facts: list[dict[str, Any]], year: int, plan: Any, *, legacy: bool) -> dict[str, Any]:
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
        "citations": _lookup_citations(fact, legacy=legacy),
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
    if [step["inputs"] for step in steps] != _growth_inputs(current_id, prior_id):
        return invalid
    return {"operation": "growth", **calculate_growth(
        source, prior_year, current_year, equal_length=request.get("equal_length", False),
    )}


def _growth_inputs(current: str, prior: str) -> list[list[str]]:
    return [[current, prior], ["subtract", prior], ["divide"]]


def _execute(
    source: dict[str, Any], facts: list[dict[str, Any]], request: ResolvedRequest, proposal: str,
    *, legacy_lookup: bool = False,
) -> dict[str, Any]:
    plan = _parse_plan(proposal)
    if request["operation"] == "lookup":
        return _execute_lookup(facts, request["fiscal_year"], plan, legacy=legacy_lookup)
    return _execute_growth(source, facts, request, plan)


def _identity(source: dict[str, Any]) -> dict[str, Any]:
    return {key: source.get(key) for key in ("source_id", "source_hash", "parser_version", "evidence_version")}


def _record_version(source: dict[str, Any], request: ResolvedRequest) -> int:
    if request["operation"] == "lookup" and source.get("parser_version") == LEGACY_STATEMENT_PARSER:
        return STATEMENT_LOOKUP_RECORD_VERSION
    if request["operation"] == "growth" and source.get("parser_version") in dated_revenue.FILING_SCOPED_PARSERS:
        if source.get("parser_version") in dated_revenue.ORIGINAL_EVIDENCE_PARSERS:
            return ORIGINAL_GROWTH_RECORD_VERSION
        return DATED_GROWTH_RECORD_VERSION
    return RECORD_VERSION


def _legacy_dated_lookup_gap(
    source: dict[str, Any], facts: list[dict[str, Any]], request: ResolvedRequest,
) -> dict[str, Any] | None:
    if request["operation"] != "lookup" or source.get("parser_version") not in dated_revenue.FILING_SCOPED_PARSERS:
        return None
    year = request["fiscal_year"]
    if len(_facts_for_year(facts, year)) == 1:
        return None
    reasons = [item["message"] for item in source["diagnostics"] if item.get("fiscal_year", year) == year]
    for fact in _facts_for_year(source["facts"], year):
        reasons.extend(fact["unresolved_requirements"])
    if not reasons:
        reasons.append("No unique annual revenue observation was found for the requested fiscal year.")
    return {"status": "evidence_unavailable", "message": f"FY{year} revenue evidence gap. " + " ".join(reasons)}


def _lookup_gap(source: dict[str, Any], eligible: list[dict[str, Any]], year: int) -> dict[str, Any] | None:
    if len(_facts_for_year(eligible, year)) == 1:
        return None
    candidates = _facts_for_year(annual_revenue_facts(source), year)
    reason, message = observation_gap(source, year, candidates)
    return {
        "status": "evidence_unavailable", "fiscal_year": year, "reason": reason, "message": message,
        "citations": [statement_period_citation(source)] if reason == "absent" else [],
    }


def _question_gap(
    source: dict[str, Any], facts: list[dict[str, Any]], request: ResolvedRequest,
    *, legacy: bool = False,
) -> dict[str, Any] | None:
    if request["operation"] == "lookup":
        if legacy:
            return _legacy_dated_lookup_gap(source, facts, request)
        return _lookup_gap(source, facts, request["fiscal_year"])
    growth = assess_growth(source, request["prior_year"], request["current_year"],
                           equal_length=request.get("equal_length", False), legacy_gaps=legacy)
    if growth["status"] == "unavailable":
        return {"operation": "growth", **growth}
    return None


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
    evidence, payload = _planner_input(source, facts, request)
    proposal = None
    model_ms = None
    execution_start: float | None = perf_counter()
    outcome = _question_gap(source, facts, request)
    version = EVIDENCE_GAP_RECORD_VERSION if outcome is not None else _record_version(source, request)
    if outcome is None:
        execution_start = None
        model_start = perf_counter()
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
        model_ms = round(((execution_start or perf_counter()) - model_start) * 1000, 3)
    end = perf_counter()
    result = {**_identity(source), **outcome}
    if record is not None:
        record.update({
            "version": version,
            "question": question,
            "resolved_request": request,
            "source": _identity(source),
            "evidence": evidence,
            "model_settings": {"expected_server_configuration": MODEL_SETTINGS},
            "model_request": payload if model_ms is not None else None,
            "proposed_plan": proposal,
            "validation_status": outcome["status"],
            "result": result,
            "timings_ms": {
                "model": model_ms,
                "validation_and_execution": round((end - execution_start) * 1000, 3)
                if execution_start is not None else None,
                "total": round((end - start) * 1000, 3),
            },
        })
    return result


def _matches_legacy_dated_payload(saved: dict[str, Any], expected: dict[str, Any]) -> bool:
    try:
        messages = saved["messages"]
        user_message = messages[1]
        content = expected["messages"][1]["content"]
        if json.loads(user_message["content"], object_pairs_hook=_unique_keys) != json.loads(content):
            return False
        normalized = [*messages[:1], user_message | {"content": content}, *messages[2:]]
    except (ValueError, TypeError, KeyError, IndexError, RecursionError):
        return False
    return saved | {"messages": normalized} == expected


def replay_revenue(source: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    question, proposal = record.get("question"), record.get("proposed_plan")
    if not isinstance(question, str):
        raise SourceError("The validation record must contain a supported saved question.")
    request = resolve_request(question)
    if request is None or record.get("resolved_request") != request:
        raise SourceError("The saved request does not match its question.")
    version = record.get("version")
    expected_version = _record_version(source, request)
    old_original_growth = (version == DATED_GROWTH_RECORD_VERSION
                           and expected_version == ORIGINAL_GROWTH_RECORD_VERSION)
    if version not in (RECORD_VERSION, expected_version, EVIDENCE_GAP_RECORD_VERSION) and not old_original_growth:
        raise SourceError("The validation record must contain a supported saved question.")
    if old_original_growth:
        source = source | {"comparison": dated_revenue.legacy_comparison()}
    legacy_growth = version == RECORD_VERSION and expected_version == DATED_GROWTH_RECORD_VERSION
    facts = _eligible_facts(source)
    evidence, expected_payload = _planner_input(source, facts, request, legacy_growth=legacy_growth)
    identity = _identity(source)
    if record.get("source") != identity or record.get("evidence") != evidence:
        raise SourceError("The saved source or evidence does not match the current filing evidence.")
    saved_payload = record.get("model_request")
    # Older records may contain a model proposal for a growth question with missing evidence.
    if version == EVIDENCE_GAP_RECORD_VERSION:
        gap = _question_gap(source, facts, request)
        if gap is None:
            raise SourceError("The saved evidence gap does not match the current filing evidence.")
    else:
        gap = (_question_gap(source, facts, request, legacy=True) if saved_payload is None
               else _legacy_dated_lookup_gap(source, facts, request))
    if gap is not None:
        if "proposed_plan" not in record or proposal is not None or "model_request" not in record or saved_payload is not None:
            raise SourceError("The saved evidence gap must record that no model request was made.")
        return {**identity, **gap}
    if not isinstance(saved_payload, dict) or not isinstance(saved_payload.get("model"), str):
        raise SourceError("The validation record must contain its original model request.")
    # The alias identifies the original planner. Replay validates the proposal with no model loaded.
    expected_payload["model"] = saved_payload["model"]
    legacy_dated = version == RECORD_VERSION and source.get("parser_version") == dated_revenue.PARSER_VERSION
    if saved_payload != expected_payload and not (
        legacy_dated and _matches_legacy_dated_payload(saved_payload, expected_payload)
    ):
        raise SourceError("The saved source or evidence does not match the current filing evidence.")
    if not isinstance(proposal, str):
        raise SourceError("The validation record must contain a supported saved proposal.")
    if legacy_growth:
        source = source | {"comparison": dated_revenue.legacy_comparison()}
    outcome = _execute(source, facts, request, proposal, legacy_lookup=version == RECORD_VERSION)
    if legacy_growth and outcome["status"] == "unavailable":
        outcome["citations"] = []
    return {**identity, **outcome}


replay_lookup = replay_revenue
