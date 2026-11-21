"""Calculate reported revenue growth from a selected filing's verified evidence."""

from decimal import Context, Decimal
from fractions import Fraction
from typing import Any

from frag.store import SourceError

FORMULA = "(current revenue - prior revenue) / prior revenue × 100"


def calculate_growth(source: dict[str, Any], prior_year: int, current_year: int) -> dict[str, Any]:
    if not 1 <= prior_year < current_year <= 9999:
        raise SourceError("Choose fiscal years with the prior year before the current year.")

    facts = [
        fact for fact in source.get("facts", [])
        if fact["source_id"] == source["source_id"]
        and fact["metric"] == "reported_consolidated_revenue"
        and fact["reporting_period"]["kind"] == "annual"
    ]
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
        "comparison_basis": comparison.get("basis"),
        "scope_caveats": comparison.get("scope_caveats", []),
    }
    selected = []
    for role, year in (("prior", prior_year), ("current", current_year)):
        candidates = [fact for fact in facts if fact["reporting_period"]["fiscal_year"] == year]
        if len(candidates) != 1:
            issue = {"code": "missing" if not candidates else "incompatible", "role": role, "fiscal_year": year}
            if candidates:
                issue["detail"] = f"Multiple reported consolidated revenue observations match FY{year}."
            result["issues"].append(issue)
            continue
        fact = candidates[0]
        result["operands"].append({"role": role, **fact})
        selected.append(fact)
        if (fact["status"] != "verified" or fact["normalized_amount"] is None
                or not fact["currency"] or not fact["scale"]):
            result["issues"].append({"code": "unverified", "role": role, "fiscal_year": year})

    if result["issues"]:
        result["status"] = "unavailable"
        return result

    prior, current = selected
    detail = _comparison_issue(comparison, facts, prior, current)
    if detail:
        result["status"] = "unavailable"
        result["issues"].append({
            "code": "incompatible", "role": None, "fiscal_year": None, "detail": detail,
        })
        return result

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
    result["citations"] = _citations(result["operands"], comparison)

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
    if comparison.get("status") != "compatible":
        requirements = ", ".join(item.replace("_", " ") for item in comparison.get("unresolved_requirements", []))
        message = "The filing's comparison evidence does not establish compatibility."
        return f"{message} Open requirements · {requirements}" if requirements else message
    # The existing verifier's comparison applies to the single extracted pair.
    if len(facts) != 2 or not prior["comparative"] or current["comparative"]:
        return "The selected fiscal years do not match the filing's verified comparative and current pair."
    if prior["currency"] != current["currency"]:
        return f'The verified revenue amounts use different currencies ({prior["currency"]} and {current["currency"]}).'
    return None


def _citations(operands: list[dict[str, Any]], comparison: dict[str, Any]) -> list[dict[str, Any]]:
    citations: dict[str, dict[str, Any]] = {}
    for fact in operands:
        year = fact["reporting_period"]["fiscal_year"]
        citations[fact["role"]] = {
            "id": fact["role"],
            "title": f'FY{year} {fact["metric_label"]} cell',
            "locator": fact["locators"]["value"],
            "context_locators": {
                key: fact["locators"][key] for key in ("metric_label", "year_header", "unit_header")
            },
        }
    for fact in operands:
        for note in fact["applicable_notes"]:
            number = note["number"]
            citation_id = f"note-{number}"
            citations[citation_id] = {
                "id": citation_id, "title": f'Note {number} · {note["title"]}', "locator": note["locator"],
            }
    for disclosure in comparison.get("evidence", []):
        citation_id = disclosure["id"]
        citations[citation_id] = {
            "id": citation_id,
            "title": disclosure["id"].replace("_", " ").capitalize(),
            "locator": disclosure["locator"],
        }
    return list(citations.values())
