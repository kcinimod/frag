"""Calculate reported revenue growth from a selected filing's verified evidence."""

from datetime import date
from decimal import Context, Decimal
from fractions import Fraction
from typing import Any

from frag.citations import has_citable_amount, revenue_cell_citation, statement_period_citation
from frag.revenue import PARSER_VERSION as LEGACY_STATEMENT_PARSER
from frag.store import SourceError

FORMULA = "(current revenue - prior revenue) / prior revenue × 100"
METRIC = "reported_consolidated_revenue"


def annual_revenue_facts(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        fact for fact in source.get("facts", [])
        if fact["source_id"] == source["source_id"] and fact["metric"] == METRIC
        and fact["reporting_period"]["kind"] == "annual"
    ]


def assess_growth(
    source: dict[str, Any], prior_year: int, current_year: int, *, equal_length: bool = False,
    legacy_gaps: bool = False,
) -> dict[str, Any]:
    """Resolve operands and check eligibility without executing a calculation."""
    if not 1 <= prior_year < current_year <= 9999:
        raise SourceError("Choose fiscal years with the prior year before the current year.")

    facts = annual_revenue_facts(source)
    comparison = source.get("comparison") or {}
    result: dict[str, Any] = {
        **{key: source.get(key) for key in ("source_id", "source_hash", "parser_version", "evidence_version")},
        "prior_year": prior_year,
        "current_year": current_year,
        "formula": FORMULA,
        "operands": [],
        "issues": [],
        "trace": [],
        "percent": None,
        "absolute_change": None,
        "citations": [],
        "comparison_basis": None,
        "scope_caveats": [],
    }
    selected = []
    for role, year in (("prior", prior_year), ("current", current_year)):
        candidates = [fact for fact in facts if fact["reporting_period"]["fiscal_year"] == year]
        fact = candidates[0] if len(candidates) == 1 else None
        supported = fact is not None and fact["status"] == "verified" and has_citable_amount(fact)
        if fact is not None and (supported or legacy_gaps):
            result["operands"].append({"role": role, **fact})
            selected.append(fact)
        if not supported:
            code, reason = (_legacy_growth_gap(source, year, candidates) if legacy_gaps
                            else observation_gap(source, year, candidates))
            result["issues"].append({"code": code, "role": role, "fiscal_year": year, "detail": reason})

    if not result["issues"]:
        prior, current = selected
        detail = _comparison_issue(comparison, facts, prior, current)
        if detail is None and equal_length:
            detail = _equal_length_issue(prior, current)
        if detail:
            result["issues"].append({
                "code": "incompatible", "role": None, "fiscal_year": None, "detail": detail,
            })

    if result["issues"]:
        result["status"] = "unavailable"
        supported = [fact for fact in result["operands"] if fact["status"] == "verified" and has_citable_amount(fact)]
        comparison_evidence = comparison if (
            comparison.get("status") == "unresolved" and _matches_comparison_pair(comparison.get("fact_ids", []), supported)
        ) else {}
        result["citations"] = _citations(supported, comparison_evidence)
        if any(issue["code"] == "absent" for issue in result["issues"]):
            result["citations"].append(statement_period_citation(source))
    else:
        result.update(status="ready", comparison_basis=comparison.get("basis"),
                      scope_caveats=comparison.get("scope_caveats", []))
    return result


def observation_gap(source: dict[str, Any], year: int, candidates: list[dict[str, Any]]) -> tuple[str, str]:
    periods = (source.get("statement_periods") or {}).get("period_headers")
    if periods and str(year) not in periods and not candidates:
        listed = ", ".join(f"FY{period}" for period in sorted(periods))
        return ("absent", f"FY{year} is absent from the consolidated revenue statement. "
                f"The statement shows {listed}.")
    if len(candidates) > 1:
        explanation = "Multiple reported consolidated revenue observations match the requested year."
    elif candidates:
        explanation = "The extracted observation could not be verified."
    elif periods:
        explanation = "The statement shows this year, but extraction did not produce a revenue observation."
    else:
        explanation = "The available evidence did not establish the statement periods or a revenue observation."
    reasons = [
        item["message"] for item in source.get("diagnostics", [])
        if item.get("fiscal_year", year) == year
        and (source.get("parser_version") != LEGACY_STATEMENT_PARSER or "fiscal_year" in item)
    ]
    for fact in candidates:
        reasons.extend({
            "applicable_notes": "The applicable filing disclosures need verification.",
        }.get(item, item.replace("_", " ") + ".") for item in fact.get("unresolved_requirements", []))
    detail = " ".join(dict.fromkeys([explanation, *reasons]))
    return "unverified", f"FY{year} revenue evidence gap. {detail}"


def _legacy_growth_gap(source: dict[str, Any], year: int, candidates: list[dict[str, Any]]) -> tuple[str, str]:
    if len(candidates) > 1:
        return "incompatible", f"Multiple reported consolidated revenue observations match FY{year}."
    fact = candidates[0] if candidates else None
    reasons = [
        item["message"] for item in source.get("diagnostics", [])
        if item.get("fiscal_year", year) == year
    ]
    if fact is not None:
        reasons.extend(fact.get("unresolved_requirements", []))
    if not reasons:
        reasons.append("No unique annual revenue observation was found." if fact is None
                       else "The annual revenue observation has not passed verification.")
    return ("unverified" if fact is not None else "missing"), f"FY{year} revenue evidence gap. " + " ".join(reasons)


def calculate_growth(
    source: dict[str, Any], prior_year: int, current_year: int, *, equal_length: bool = False,
) -> dict[str, Any]:
    result = assess_growth(source, prior_year, current_year, equal_length=equal_length)
    if result["status"] == "unavailable":
        return result

    prior, current = result["operands"]
    baseline = Decimal(prior["normalized_amount"])
    latest = Decimal(current["normalized_amount"])
    # Align decimal places and subtract independently of the caller's arithmetic context.
    places = min(baseline.as_tuple().exponent, latest.as_tuple().exponent)
    precision = max(baseline.adjusted(), latest.adjusted()) - int(places) + 2
    change = Context(prec=precision).subtract(latest, baseline)
    amount = format(change, "f")
    result["trace"].append({
        "operation": "subtract", "inputs": [current["fact_id"], prior["fact_id"]], "result": amount,
    })
    result["citations"] = _citations(result["operands"], source["comparison"])

    if not baseline:
        result["status"] = "undefined_zero_baseline"
        result["absolute_change"] = {"currency": prior["currency"], "value": amount}
        return result

    ratio = Fraction(change) / Fraction(baseline)
    percent = format(ratio * 100, ".2f")
    result["trace"].extend([
        {"operation": "divide", "inputs": ["subtract", prior["fact_id"]], "result": str(ratio)},
        {"operation": "to_percent", "inputs": ["divide"], "result": percent},
    ])
    result["status"] = "calculated"
    result["percent"] = {"unit": "percent", "value": percent}
    return result


def _comparison_issue(
    comparison: dict[str, Any], facts: list[dict[str, Any]], prior: dict[str, Any], current: dict[str, Any],
) -> str | None:
    # Older verifiers reviewed their only extracted pair. Newer records identify it explicitly.
    fact_ids = comparison.get("fact_ids", [fact["fact_id"] for fact in facts])
    matches = _matches_comparison_pair(fact_ids, [prior, current])
    if "fact_ids" in comparison and not matches:
        return "The selected fiscal years do not match the filing's verified comparative and current pair."
    if comparison.get("status") != "compatible":
        if comparison.get("detail"):
            return str(comparison["detail"])
        requirements = ", ".join(item.replace("_", " ") for item in comparison.get("unresolved_requirements", []))
        message = "The filing's comparison evidence does not establish compatibility."
        return f"{message} Open requirements · {requirements}" if requirements else message
    if not matches or not prior["comparative"] or current["comparative"]:
        return "The selected fiscal years do not match the filing's verified comparative and current pair."
    if prior["currency"] != current["currency"]:
        return f'The verified revenue amounts use different currencies ({prior["currency"]} and {current["currency"]}).'
    return None


def _matches_comparison_pair(fact_ids: list[str], operands: list[dict[str, Any]]) -> bool:
    return len(fact_ids) == len(operands) == 2 and set(fact_ids) == {fact["fact_id"] for fact in operands}


def _equal_length_issue(prior: dict[str, Any], current: dict[str, Any]) -> str | None:
    periods = [fact["reporting_period"] for fact in (prior, current)]
    if any(not period.get("start") or not period.get("end") for period in periods):
        return "The original evidence does not establish that the fiscal years have equal length."
    durations = [(date.fromisoformat(period["end"]) - date.fromisoformat(period["start"])).days + 1
                 for period in periods]
    if durations[0] == durations[1]:
        return None
    lengths, unit = durations, "days"
    if all(days % 7 == 0 for days in durations):
        lengths, unit = [days // 7 for days in durations], "weeks"
    spans = [f'FY{period["fiscal_year"]} spans {length} {unit}'
             for period, length in zip(periods, lengths, strict=True)]
    return f"{spans[0]} and {spans[1]}. The reported annual amounts do not meet the requested equal-length comparison."


def _citations(operands: list[dict[str, Any]], comparison: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *(revenue_cell_citation(fact, fact["role"]) for fact in operands),
        *disclosure_citations(operands, comparison).values(),
    ]


def disclosure_citations(facts: list[dict[str, Any]], comparison: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        note_citation_id(note): {
            "id": note_citation_id(note), "title": f'Note {note["number"]} · {note["title"]}',
            "locator": note["locator"],
        }
        for fact in facts for note in fact["applicable_notes"]
    } | {
        item["id"]: {"id": item["id"], "title": item["id"].replace("_", " ").capitalize(),
                     "locator": item["locator"]}
        for item in comparison.get("evidence", [])
    }


def note_citation_id(note: dict[str, Any]) -> str:
    return str(note.get("id", f'note-{note["number"]}'))
