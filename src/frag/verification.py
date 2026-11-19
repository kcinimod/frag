"""Verify the selected revenue observations against independently inspected source spans."""

import hashlib
import json
from copy import deepcopy
from importlib.resources import files
from typing import Any

from frag.revenue import extract_revenue, matches_microsoft_company

REFERENCE = json.loads(
    files("frag").joinpath("microsoft-revenue-reference.json").read_text(encoding="utf-8")
)
EVIDENCE_VERSION: str = REFERENCE["evidence_version"]


def _matches_digest(text: str, expected: str) -> bool:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() == expected


def _matches_anchor(lines: list[str], anchor: dict[str, Any]) -> bool:
    locator = anchor["locator"]
    line, offset = locator["line"] - 1, locator["character"] - 1
    return line < len(lines) and _matches_digest(
        lines[line][offset:offset + anchor["length"]], anchor["sha256"],
    )


def _matches_span(lines: list[str], span: dict[str, Any]) -> bool:
    locator = span["locator"]
    start = locator["start"]["line"] - 1
    end = locator["end_exclusive"]["line"] - 1
    return end < len(lines) and _matches_digest(
        "\n".join(lines[start:end]) + "\n", span["sha256"],
    )


def _source_requirements(
    lines: list[str], source: dict[str, Any], synthetic: bool,
) -> list[str]:
    identity = REFERENCE["identity"]
    unresolved = []
    if not synthetic and source["source_hash"] != identity["source_hash"]:
        unresolved.append("source_identity_verification")
    if not all(_matches_anchor(lines, anchor) for anchor in REFERENCE["cover_anchors"].values()):
        unresolved.append("reference_filing_cover")
    if not matches_microsoft_company(source["company"]):
        unresolved.append("supplied_company_conflict")
    for key in ("accession", "form", "filing_date"):
        if source[key] not in (None, identity[key]):
            unresolved.append(f"supplied_{key}_conflict")
    if source["source_url"] not in (None, identity["source_url"], identity["reviewed_copy_url"]):
        unresolved.append("supplied_source_url_conflict")
    return unresolved


def _applicable_notes(
    lines: list[str], unresolved: list[str],
) -> list[dict[str, Any]]:
    headings = {
        number for number, anchor in REFERENCE["note_headings"].items()
        if _matches_anchor(lines, anchor)
    }
    if len(headings) != len(REFERENCE["note_headings"]):
        unresolved.append("note_heading_inventory")
    notes = []
    for note in REFERENCE["notes"]:
        next_heading = note["next_heading"]
        end_resolves = (
            str(next_heading) in headings if next_heading is not None
            else _matches_anchor(lines, REFERENCE["after_final_note"])
        )
        if str(note["number"]) in headings and end_resolves and _matches_span(lines, note):
            notes.append(deepcopy(note))
        else:
            unresolved.append(f"note_{note['number']}_boundary_or_content")
    return notes


def _verify_fact(
    lines: list[str], fact: dict[str, Any], requirements: list[str], synthetic: bool,
) -> bool:
    year = fact["reporting_period"]["fiscal_year"]
    observation = REFERENCE["observations"][str(year)]
    fields = REFERENCE["fact_fields"] | observation["fields"]
    if not synthetic:
        fields["company"] = REFERENCE["identity"]["company"]
    unresolved = requirements.copy()
    for field, expected in fields.items():
        if fact.get(field) != expected:
            unresolved.append(f"reference_field:{field}")
    anchors = REFERENCE["statement_anchors"] | observation["anchors"]
    for label, anchor in anchors.items():
        if fact["locators"].get(label) != anchor["locator"] or not _matches_anchor(lines, anchor):
            unresolved.append(f"reference_locator:{label}")
    matched = not unresolved
    if synthetic:
        unresolved.append("original_filing")
    fact.update(
        status="provisional" if unresolved else "verified",
        reference_status="matched" if matched else "unresolved",
        unresolved_requirements=unresolved,
    )
    return matched


def inspect_revenue(original: bytes, source: dict[str, Any]) -> dict[str, Any]:
    """Extract revenue and report source, observation and comparison checks."""
    result = extract_revenue(original, source)
    comparison: dict[str, Any] = {
        "status": "unresolved", "reference_status": "unresolved",
        "basis": None, "evidence": [], "scope_caveats": [],
        "unresolved_requirements": ["supported_FY2022_and_FY2023"],
    }
    result.update(evidence_version=EVIDENCE_VERSION, comparison=comparison)
    result["unresolved_requirements"] = [
        *result["unresolved_requirements"], "comparison_compatibility",
    ]
    if not result["facts"]:
        return result

    lines = original.decode("utf-8-sig").split("\n")
    if not _matches_anchor(lines, REFERENCE["statement_anchors"]["statement_heading"]):
        return result
    synthetic = source["provenance"]["kind"] == "synthetic"
    identity_requirements = _source_requirements(lines, source, synthetic)
    fact_requirements = identity_requirements.copy()
    notes = _applicable_notes(lines, fact_requirements)
    matching_years = set()
    for fact in result["facts"]:
        fact.update(applicable_notes=notes, evidence_version=EVIDENCE_VERSION)
        if _verify_fact(lines, fact, fact_requirements, synthetic):
            matching_years.add(fact["reporting_period"]["fiscal_year"])

    both_match = matching_years == {2022, 2023}
    if both_match:
        comparison["unresolved_requirements"].clear()
    for evidence in REFERENCE["comparison_evidence"]:
        if _matches_span(lines, evidence):
            comparison["evidence"].append(deepcopy(evidence))
        else:
            comparison["unresolved_requirements"].append(evidence["id"])
    comparison["scope_caveats"] = [
        disclosure["scope_caveat"] for disclosure in notes + comparison["evidence"]
        if "scope_caveat" in disclosure
    ]
    if not comparison["unresolved_requirements"]:
        comparison["reference_status"] = "compatible"
    if synthetic:
        comparison["unresolved_requirements"].append("original_filing")
    elif comparison["reference_status"] == "compatible":
        comparison.update(status="compatible", basis=REFERENCE["comparison_basis"])

    resolved = {
        requirement for requirement, is_resolved in (
            ("source_identity_verification", not synthetic and not identity_requirements),
            ("evidence_verification", not synthetic and both_match),
            ("comparison_compatibility", comparison["status"] == "compatible"),
        ) if is_resolved
    }
    unresolved = list(dict.fromkeys(
        requirement
        for requirement in result["unresolved_requirements"] + identity_requirements
        if requirement not in resolved
    ))
    result["unresolved_requirements"] = unresolved
    result["verification_reference"] = {
        "inspection_method": REFERENCE["inspection_method"],
        "reviewed_filing": deepcopy(REFERENCE["identity"]),
        "input_kind": source["provenance"]["kind"],
    }
    result["real_source_acceptance"] = not unresolved and not synthetic
    return result
