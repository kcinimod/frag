"""Synthetic controls for the corrected SEC acceptance scorer."""

from hashlib import sha256
from typing import Any

import pytest

from artifacts.phase06 import fresh_score_v2 as scorer
from frag.citations import citation_text


def reviewed_span(original: bytes, fragment: bytes) -> dict[str, Any]:
    start = original.index(fragment)
    return {"start_byte": start, "end_byte": start + len(fragment), "sha256": sha256(fragment).hexdigest()}


def locator(original: bytes, fragment: bytes) -> dict[str, int]:
    return {"line": 1, "character": original.index(fragment) + 1}


@pytest.mark.parametrize("repeated", [
    {"status": "matched"},
    {"status": "matched", "result": {"status": "ingestion_failed", "detail": "new"}, "citations": {}},
    {"status": "matched", "result": {"status": "ingestion_failed"}, "citations": {"extra": {}}},
])
def test_ingestion_failure_requires_both_equal_replay_payloads(repeated: dict[str, Any]) -> None:
    run = {"result": {"status": "ingestion_failed"}, "citations": {}}
    scored = scorer.score_case(run, repeated, {}, {"kind": "lookup", "outcome": "answerable", "years": ["2024"]},
                               {"facts": {}}, b"", sha256(b"").hexdigest(), observations=[])
    assert not scored["offline_replay_matched"]
    assert scored["findings"] == ["offline_replay_mismatch"]


def opened(original: bytes, result: dict[str, Any]) -> dict[str, Any]:
    source = result["source_id"]
    route = f"/api/sources/{source}/growth/citations"
    return {
        cite["id"]: {
            "http_status": 200,
            "path": f'{route}/{cite["id"]}?prior={result["prior_year"]}&current={result["current_year"]}',
            "text": citation_text(original, result["source_hash"], cite),
        }
        for cite in result["citations"]
    }


@pytest.mark.parametrize("defect", [None, "swapped_year", "unreviewed_context", "wrong_prefix", "wrong_annual_header"])
def test_period_inventory_is_credited_without_the_required_companion(defect: str | None) -> None:
    heading = b"CONSOLIDATED STATEMENTS OF OPERATIONS"
    annual = b"<td>Years ended December 31</td>"
    prior, current = b"<td>2023</td>", b"<td>2024</td>"
    row = b"<td>Revenue</td>"
    original = b"<div><span>" + heading + b"</span></div>" + annual + prior + current + row
    digest = sha256(original).hexdigest()
    review = {
        "locators": {
            "statement_title_and_units": reviewed_span(original, heading),
            "period_header": reviewed_span(original, annual + prior + current),
            "revenue_row": reviewed_span(original, row),
        },
        "facts": {year: {"locators": {"period_cell": reviewed_span(original, cell)}}
                  for year, cell in (("2023", prior), ("2024", current))},
        "applicable_notes": [],
    }
    citation: dict[str, Any] = {
        "id": "statement-periods", "title": "Consolidated revenue statement periods",
        "locator": locator(original, prior if defect == "swapped_year" else current),
        "context_locators": {
            "statement_heading": locator(original, b"<div>"),
            "metric_label": {**locator(original, row), "cell": 1},
            "annual_header": {**locator(original, annual), "cell": 1},
            "year_2023": {**locator(original, current if defect == "swapped_year" else prior), "cell": 1},
        },
    }
    if defect == "unreviewed_context":
        citation["context_locators"]["extra"] = {**locator(original, row), "cell": 1}
    if defect == "wrong_prefix":
        citation["context_locators"]["date_prefix_2023"] = {**locator(original, current), "cell": 1}
    if defect == "wrong_annual_header":
        citation["context_locators"]["annual_header"] = {**locator(original, current), "cell": 1}
    result = {
        "status": "unavailable", "source_id": f"sha256:{digest}", "source_hash": digest,
        "prior_year": 2022, "current_year": 2024, "citations": [citation],
        "issues": [{
            "code": "absent", "role": "prior", "fiscal_year": 2022,
            "detail": "FY2022 is absent from the consolidated revenue statement. The statement shows FY2023, FY2024.",
        }],
    }
    label = {"kind": "growth", "outcome": "absent_year", "years": ["2022", "2024"], "partial_years": [2024]}
    run = {"result": result, "citations": opened(original, result)}
    scored = scorer.score_case(run, {"status": "matched", **run},
                               {}, label, review, original, digest, observations=[])
    assert scored["citations_supported"] is (defect is None)
    assert scored["findings"] == (["unsupported_citation"] if defect else [])
    assert scored["incomplete_findings"] == ["missing_required_companion"]
    assert not scored["grounded_abstention"]


@pytest.mark.parametrize(
    ("caveat_year", "note_number", "defect", "expected"),
    [
        (2024, 4, None, []),
        (2024, 4, "direct_disclosure", []),
        (2023, 4, None, ["unsupported_comparison_claim"]),
        (2024, 7, None, ["unsupported_comparison_claim"]),
        (2024, 4, "wrong_operand", ["wrong_answer"]),
        (2024, 4, "wrong_inline_anchor", ["wrong_answer"]),
        (2024, 4, "wrong_statement_heading", ["unsupported_citation"]),
        (2024, 4, "overbroad_note", ["unsupported_citation", "unsupported_comparison_claim"]),
    ],
)
def test_growth_caveats_and_stops_use_reviewed_evidence(
    caveat_year: int, note_number: int, defect: str | None, expected: list[str],
) -> None:
    heading = b"<div>Consolidated Statements of Operations</div><div>USD in millions</div>"
    fiscal_row = b"<td>2023</td><td>2024</td>"
    revenue_row = b"<td>Revenue</td><td>100</td><td>120</td>"
    table = b"<table>" + fiscal_row + revenue_row + b"</table>"
    acquisition = (
        b"Our Consolidated Statements of Operations for fiscal 2024 includes revenue attributable to Example "
        b"since the date of acquisition." if defect == "direct_disclosure" else
        b"On March 1, 2024, the company acquired Example after signing an agreement in 2023. "
        b"Example revenue is included from the acquisition date."
    )
    text = (b"<div>Note 4. " + acquisition
            + b" Supplemental pro forma results use the combination period described above.</div>")
    unrelated = b"<table><td>Unrelated table and disclosures</td></table>"
    evidence_prefix = (
        b"<xbrli:measure>iso4217:USD</xbrli:measure>"
        b"<xbrli:context id='prior'>2023</xbrli:context>"
        b"<xbrli:context id='current'>2024</xbrli:context>"
    )
    original = evidence_prefix + heading + table + text + unrelated
    digest = sha256(original).hexdigest()
    source = f"sha256:{digest}"
    review: dict[str, Any] = {
        "locators": {
            "statement": reviewed_span(original, table),
            "statement_title_and_units": reviewed_span(original, heading),
            "period_header": reviewed_span(original, fiscal_row),
            "revenue_row": reviewed_span(original, revenue_row),
        },
        "applicable_notes": [{"label": "Note 4. Acquisitions", "locator": reviewed_span(original, text)}],
        "facts": {},
    }
    intake: dict[str, Any] = {"facts": []}
    citations: list[dict[str, Any]] = []
    for role, year, raw in [("prior", 2023, "100"), ("current", 2024, "120")]:
        cell = f"<td>{raw}</td>".encode()
        period = f"<td>{year}</td>".encode()
        context = f"<xbrli:context id='{role}'>{year}</xbrli:context>".encode()
        unit = b"<xbrli:measure>iso4217:USD</xbrli:measure>"
        start, end = f"{year}-01-01", f"{year}-12-31"
        locators = {
            "value": {**locator(original, cell), "cell": 1},
            "year_header": {**locator(original, period), "cell": 1},
            "table": locator(original, table), "metric_label": {**locator(original, b"<td>Revenue"), "cell": 1},
            "unit_header": locator(original, b"<div>USD"), "currency_measure": locator(original, unit),
            "inline_fact": locator(original, cell), "inline_context": locator(original, context),
        }
        reference = {
            "fiscal_year": year, "raw_amount": raw, "scale": 1000000, "currency": "USD", "scope": "consolidated",
            "period_start": start, "period_end": end, "normalized_amount": raw + "000000",
            "verification": "inline_corroborated", "element_id": role, "context_id": role, "concept": "Revenue",
            "locators": {key: reviewed_span(original, fragment) for key, fragment in
                         [("statement_cell", cell), ("period_cell", period), ("inline_fact", cell),
                          ("context", context), ("unit", unit)]},
        }
        review["facts"][str(year)] = reference
        intake["facts"].append({
            "fact_id": role, "source_id": source, "status": "verified", "metric": "reported_consolidated_revenue",
            "scope": "consolidated", "raw_amount": raw, "normalized_amount": raw + "000000",
            "currency": "USD", "scale": 1000000, "locators": locators,
            "inline_xbrl": {"fact_element_id": role, "context_id": role, "concept": "Revenue"},
            "reporting_period": {"kind": "annual", "fiscal_year": year, "start": start, "end": end},
        })
        citations.append({
            "id": role, "title": f"FY{year} revenue", "locator": locators["value"],
            "context_locators": {key: locators[key] for key in ("year_header", "metric_label", "unit_header",
                                                               "currency_measure")},
        })
    citations.append({
        "id": "note-4", "title": "Note 4", "locator": {
            "start": locator(original, text), "end_exclusive": locator(original, unrelated),
        },
    })
    for fact in intake["facts"]:
        fact["applicable_notes"] = [{"locator": citations[-1]["locator"]}]
    if defect == "wrong_inline_anchor":
        intake["facts"][0]["locators"]["currency_measure"] = locator(original, b"<table>")
    observed = scorer.audit_observations(original, {"source_id": source, "sha256": digest}, review, intake)
    operands = [{**fact, "role": fact["fact_id"]} for fact in intake["facts"]]
    if defect == "wrong_operand":
        operands[0]["normalized_amount"] = "90000000"
    if defect == "wrong_statement_heading":
        citations[0]["context_locators"]["statement_heading"] = locator(original, text)
    if defect == "overbroad_note":
        citations[-1]["locator"] = {**citations[-1]["locator"], "end_exclusive": {"line": 1, "character": len(original) + 1}}
    result: dict[str, Any] = {
        "status": "calculated", "source_id": source, "source_hash": digest, "prior_year": 2023, "current_year": 2024,
        "citations": citations, "operands": operands, "formula": "(current revenue - prior revenue) / prior revenue × 100",
        "percent": {"value": "20", "unit": "percent"}, "trace": [
            {"operation": "subtract", "inputs": ["current", "prior"], "result": "20000000"},
            {"operation": "divide", "inputs": ["subtract", "prior"], "result": "1/5"},
            {"operation": "to_percent", "inputs": ["divide"], "result": "20"},
        ],
        "comparison_basis": "Consecutive annual consolidated revenue amounts from the same statement and reporting basis.",
        "scope_caveats": [
            "Growth uses reported consolidated amounts, including any effects of exchange rates or acquisitions.",
            f"FY{caveat_year} includes Example revenue from the acquisition date.",
            f"Supplemental pro forma results use the combination period described in Note {note_number}.",
        ],
    }
    label = {"kind": "growth", "outcome": "answerable", "years": ["2023", "2024"],
             "absolute_change": "20000000", "percent": "20"}
    run = {"result": result, "citations": opened(original, result)}
    scored = scorer.score_case(run, {"status": "matched", **run}, intake, label, review, original, digest,
                               observations=observed)
    assert scored["findings"] == expected
    assert scored["end_to_end_complete"] == (not expected)
    assert scored["citations_supported"] is ("unsupported_citation" not in expected)
    stages = scorer.classify(run, intake, label, scored, observed)
    assert stages["observations_extracted"] == {"2023": True, "2024": True}
    assert stages["observations_verified"] == {"2023": defect != "wrong_inline_anchor", "2024": True}
    assert stages["first_failure_stage"] == (
        "verification" if defect == "wrong_inline_anchor"
        else "execution" if defect == "wrong_operand" else "presentation" if expected else "complete"
    )
    if expected:
        return

    # A wrong comparison reason blocks completion while the independently cited operands retain credit.
    result.update(status="unavailable", percent=None, trace=[], scope_caveats=[], comparison_basis=None, issues=[
        {"code": "incompatible", "role": None, "fiscal_year": None, "detail": "FY2024 spans 51 weeks."},
    ])
    scored = scorer.score_case(run, {"status": "matched", **run}, intake, {
        **label, "outcome": "incompatible_periods", "period_weeks": [52, 53], "partial_years": [2023, 2024],
    }, review, original, digest, observations=observed)
    assert scored["supported_companions"] == ["current", "prior"]
    assert scored["findings"] == ["contradicted_abstention"]
    assert not scored["end_to_end_complete"]


@pytest.mark.parametrize("case", ["supported", "extraction_gap", "pending_verification", "wrong_reason"])
def test_displayed_unverifiable_revenue_requires_the_reviewed_reason(case: str) -> None:
    year = 2018
    original = b"<table><tr><td>2018</td><td>Revenue</td><td>100</td></tr></table>"
    digest = sha256(original).hexdigest()
    source = f"sha256:{digest}"
    fact = {"fiscal_year": year, "verification": "provisional"}
    observed = None if case == "extraction_gap" else {"status": "provisional", "inline_xbrl": None}
    observations = [{"expected": fact, "observed": observed, "extraction_matched": observed is not None,
                     "reusable_verification_matched": False}]
    explanation = {
        "supported": ("The extracted observation could not be verified. The consolidated statement displays revenue "
                      "for this year, but the original lacks the inline XBRL fact, context, and unit needed for "
                      "verification. Inline xbrl verification."),
        "wrong_reason": "The extracted observation could not be verified. The original has mismatched units.",
        "extraction_gap": "The available evidence did not establish the statement periods or a revenue observation.",
        "pending_verification": "Verification is pending.",
    }
    result = {
        "status": "evidence_unavailable", "reason": "unverified", "fiscal_year": year,
        "source_id": source, "source_hash": digest,
        "message": f"FY2018 revenue evidence gap. {explanation[case]}",
    }
    run = {"result": result, "citations": {}}
    label = {
        "kind": "lookup", "outcome": "present_unverifiable", "years": ["2018"],
        "reason": "The preserved original has no matching inline XBRL fact, context, and unit.",
    }
    intake: dict[str, Any] = {}
    scored = scorer.score_case(run, {"status": "matched", **run}, intake, label,
                               {"facts": {"2018": fact}, "applicable_notes": []}, original, digest,
                               observations=observations)
    assert scored["grounded_abstention"] is (case == "supported")
    assert scored["findings"] == (["contradicted_abstention"] if case == "wrong_reason" else [])
    assert scored["incomplete_findings"] == (
        ["missing_required_verification_reason"] if case in {"extraction_gap", "pending_verification"} else []
    )
    assert scorer.classify(run, intake, label, scored, observations)["first_failure_stage"] == {
        "supported": "complete", "extraction_gap": "extraction", "pending_verification": "verification",
        "wrong_reason": "verification",
    }[case]
