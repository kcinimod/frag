"""Score filing-scoped revenue results with the Phase 6 acceptance policy."""

from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase05"))

from acceptance_score import observation_matches, score_case as phase05_score_case  # type: ignore[import-not-found]
from holdout_score import evidence_gap  # type: ignore[import-not-found]

FULL_DATE_DIAGNOSTIC = "Expected one row of full dates below Years ended."


def gap_matches(text: str, year: str, review: dict[str, Any], evidence: dict[str, Any]) -> bool:
    periods = (evidence.get("statement_periods") or {}).get("period_headers")
    if periods and (year not in periods or text.startswith(
        f"FY{year} revenue evidence gap. The available evidence did not establish the statement periods"
    )):
        return False
    suffix = f" {FULL_DATE_DIAGNOSTIC}"
    if text.endswith(suffix) and any(
        item.get("code") == "unsupported_layout" and item.get("message") == FULL_DATE_DIAGNOSTIC
        and item.get("fiscal_year", int(year)) == int(year)
        for item in evidence.get("diagnostics", [])
    ):
        text = text.removesuffix(suffix)
    return bool(evidence_gap(text, year, review["facts"], evidence))


def truthful_gap(
    result: dict[str, Any], label: dict[str, Any], review: dict[str, Any], evidence: dict[str, Any],
) -> bool:
    if label["kind"] == "lookup":
        return (result.get("status") == "evidence_unavailable" and result.get("reason") == "unverified"
                and gap_matches(result.get("message", ""), label["years"][0], review, evidence))
    roles = dict(zip(("prior", "current"), label["years"], strict=True))
    issues = result.get("issues", [])
    return (result.get("status") == "unavailable" and bool(issues)
            and len({item.get("role") for item in issues}) == len(issues) and all(
        item.get("code") == "unverified" and item.get("role") in roles
        and item.get("fiscal_year") == int(roles[item["role"]])
        and gap_matches(item.get("detail", ""), roles[item["role"]], review, evidence)
        for item in issues
    ))


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
           and not scored["numeric_answer_emitted"] and truthful_gap(result, label, review, evidence))
    if gap and "contradicted_abstention" in findings:
        findings.remove("contradicted_abstention")
    if gap and not answerable and not findings and scored["citations_supported"]:
        scored["grounded_abstention"] = scored["end_to_end_complete"] = True

    supported_partial = False
    if answerable and label["kind"] == "growth" and not scored["numeric_answer_emitted"]:
        operands = result.get("operands", [])
        if operands and result.get("status") == "unavailable":
            if verified_companion(operands, label, review, evidence, original, original_hash):
                findings.remove("unsupported_partial")
                supported_partial = scored["citations_supported"]
    known_verification_gap = (label.get("baseline_gap") == "present_unverifiable"
                              and scored["status"] == "evidence_unavailable")
    scored["incomplete"] = answerable and (gap or known_verification_gap) and not findings
    scored["supported_partial"] = supported_partial
    return scored
