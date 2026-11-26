"""Score filing-scoped revenue results with the Phase 6 acceptance policy."""

from pathlib import Path
import sys
from typing import Any

from frag.citations import has_citable_amount
from frag.growth import annual_revenue_facts, observation_gap

# The historical scripts resolve sibling modules as top-level imports.
saved_path = sys.path.copy()
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase05"))
    from acceptance_score import observation_matches, score_case as phase05_score_case  # type: ignore[import-not-found]
finally:
    sys.path[:] = saved_path


def gap_matches(text: str, year: int, evidence: dict[str, Any], *, growth: bool) -> bool:
    candidates = [fact for fact in annual_revenue_facts(evidence) if fact["reporting_period"]["fiscal_year"] == year]
    if sum(fact["status"] == "verified" and has_citable_amount(fact) for fact in candidates) == 1 and (
        not growth or len(candidates) == 1
    ):
        return False
    # Reconstruct the detail from replayed intake evidence and keep absence under the independent reference checks.
    return observation_gap(evidence, year, candidates) == ("unverified", text)


def truthful_gap(
    result: dict[str, Any], label: dict[str, Any], evidence: dict[str, Any],
) -> bool:
    if label["kind"] == "lookup":
        return (result.get("status") == "evidence_unavailable" and result.get("reason") == "unverified"
                and gap_matches(result.get("message", ""), int(label["years"][0]), evidence, growth=False))
    roles = dict(zip(("prior", "current"), map(int, label["years"]), strict=True))
    issues = result.get("issues", [])
    if result.get("status") != "unavailable" or not issues or len({item.get("role") for item in issues}) != len(issues):
        return False
    return all(
        item.get("code") == "unverified" and item.get("role") in roles
        and item.get("fiscal_year") == roles[item["role"]]
        and gap_matches(item.get("detail", ""), roles[item["role"]], evidence, growth=True)
        for item in issues
    )


def verified_companion(
    operands: list[dict[str, Any]], label: dict[str, Any], review: dict[str, Any],
    evidence: dict[str, Any], original: bytes, original_hash: str,
) -> bool:
    if len(operands) != 1:
        return False
    fact = dict(operands[0])
    role = fact.pop("role", None)
    years = dict(zip(("prior", "current"), label["years"], strict=True))
    expected = review["facts"].get(years.get(role))
    return (expected is not None and fact.get("status") == "verified"
            and fact.get("source_id") == f"sha256:{original_hash}" and fact in evidence.get("facts", [])
            and bool(observation_matches(fact, expected, original.split(b"\n"))))


def score_case(
    run: dict[str, Any], repeated: dict[str, Any], evidence: dict[str, Any],
    label: dict[str, Any], review: dict[str, Any], original: bytes, original_hash: str,
) -> dict[str, Any]:
    scored: dict[str, Any] = phase05_score_case(run, repeated, evidence, label, review, original, original_hash)
    findings = scored["findings"]
    answerable = label["outcome"] == "answerable"
    result = run["result"]
    gap = (label["outcome"] in {"answerable", "present_unverifiable"}
           and not scored["numeric_answer_emitted"] and truthful_gap(result, label, evidence))
    if gap and "contradicted_abstention" in findings:
        findings.remove("contradicted_abstention")
    if gap and not answerable and not findings and scored["citations_supported"]:
        scored["grounded_abstention"] = scored["end_to_end_complete"] = True

    companion = (
        answerable and label["kind"] == "growth" and scored["status"] == "unavailable"
        and "unsupported_partial" in findings
        and verified_companion(result.get("operands", []), label, review, evidence, original, original_hash)
    )
    if companion:
        findings.remove("unsupported_partial")
    known_verification_gap = (label.get("baseline_gap") == "present_unverifiable"
                              and scored["status"] == "evidence_unavailable")
    scored["incomplete"] = answerable and (gap or known_verification_gap) and not findings
    scored["supported_partial"] = companion and scored["citations_supported"]
    return scored
