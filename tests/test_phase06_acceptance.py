"""Regression controls at the filing acceptance scorer's case entry point."""

import gzip
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pytest

from artifacts.phase06 import revenue_score

PHASE = Path("artifacts/phase06")
PHASE05 = PHASE.with_name("phase05")


def retained(phase: Path, name: str) -> dict[str, Any]:
    report: dict[str, Any] = json.loads(gzip.decompress((phase / f"{name}.json.gz").read_bytes()))
    return report


@pytest.mark.parametrize("kind, case_id", [("lookup", "P5-12"), ("growth", "P5-13")])
def test_retained_cisco_diagnostic_is_incomplete(kind: str, case_id: str) -> None:
    live, replay = (retained(PHASE, f"opened-{name}") for name in ("live", "replay"))
    run, repeated = (next(row for row in report["cases"] if row["case"]["case_id"] == case_id)
                     for report in (live, replay))
    source = live["sources"][run["case"]["source_id"]]["evidence"]
    original = gzip.decompress((PHASE / "originals/csco-20240727.htm.gz").read_bytes())
    # Independently established statement periods. This control has no emitted amount.
    review: dict[str, Any] = {"facts": dict.fromkeys(("2022", "2023", "2024")), "applicable_notes": []}
    label = {"kind": kind, "outcome": "answerable", "years": ["2024"] if kind == "lookup" else ["2023", "2024"]}
    historical = json.loads((PHASE / "opened-score.json").read_bytes())
    for mode in ("cold", "warm"):
        scored = revenue_score.score_case(run[mode], repeated[mode], source, label, review, original,
                                          run[mode]["result"]["source_hash"])
        assert scored["incomplete"]
        assert scored["findings"] == []
        assert not scored["end_to_end_complete"] and not scored["grounded_abstention"]
        saved = next(row for row in historical[mode]["cases"] if row["case_id"] == case_id)
        assert saved["findings"] == ["contradicted_abstention"]


@pytest.fixture
def apple_growth() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], bytes]:
    live = retained(PHASE05, "evidence-gap-live")
    row = next(row for row in live["cases"] if row["case"]["case_id"] == "aapl-growth")
    source = live["sources"][row["case"]["source_id"]]["evidence"]
    labels = json.loads((PHASE05 / "expected.json").read_bytes())
    label = labels["cases"]["aapl-growth"]
    label["presentation"] = json.loads((PHASE05 / "acceptance-text.json").read_bytes())["aapl-growth"]
    original = gzip.decompress((PHASE.parent / "phase04/development/originals/aapl-20230930.htm.gz").read_bytes())
    return row["cold"], source, label, labels["sources"][row["case"]["source_id"]], original


def test_cited_companion_is_supported_without_answer_credit(
    apple_growth: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], bytes],
) -> None:
    run, evidence, label, review, original = apple_growth
    # Synthetic control derived from a retained answer. Keep the real FY2023 evidence and opened citations.
    make_prior_extraction_gap(run, evidence)
    scored = revenue_score.score_case(run, {"status": "matched", **run}, evidence, label, review, original,
                                      sha256(original).hexdigest())
    assert scored["findings"] == []
    assert scored["incomplete"] and scored["supported_partial"]
    assert not scored["answer_accurate"] and not scored["numeric_answer_emitted"]
    assert not scored["end_to_end_complete"] and not scored["grounded_abstention"]


def make_prior_extraction_gap(run: dict[str, Any], evidence: dict[str, Any]) -> None:
    result = run["result"]
    result.update(status="unavailable", percent=None, trace=[], comparison_basis=None, scope_caveats=[], issues=[{
        "role": "prior", "fiscal_year": 2022, "code": "unverified",
        "detail": "FY2022 revenue evidence gap. The statement shows this year, but extraction did not produce "
                  "a revenue observation.",
    }])
    result["operands"] = [fact for fact in result["operands"] if fact["role"] == "current"]
    result["citations"] = [item for item in result["citations"] if item["id"] not in {"prior", "foreign_currency_impact"}]
    run["citations"] = {item["id"]: run["citations"][item["id"]] for item in result["citations"]}
    evidence["facts"] = [fact for fact in evidence["facts"] if fact["reporting_period"]["fiscal_year"] != 2022]


@pytest.mark.parametrize(
    ("fault", "finding"),
    [
        ("wrong_percent", "wrong_answer"),
        ("wrong_partial_amount", "unsupported_partial"),
        ("unverified_partial", "unsupported_partial"),
        ("unopened_partial", "unsupported_citation"),
        ("wrong_citation", "unsupported_citation"),
        ("contradicted_reason", "contradicted_abstention"),
        ("verified_year_gap", "contradicted_abstention"),
        ("wrong_replay_result", "offline_replay_mismatch"),
        ("wrong_replay_citations", "offline_replay_mismatch"),
    ],
)
def test_acceptance_keeps_blocking_findings(
    apple_growth: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], bytes],
    fault: str, finding: str,
) -> None:
    run, evidence, label, review, original = apple_growth
    if fault != "wrong_percent":
        make_prior_extraction_gap(run, evidence)
    result = run["result"]
    if fault == "wrong_percent":
        result["percent"]["value"] = "-2.81"
    elif fault == "wrong_partial_amount":
        result["operands"][0]["normalized_amount"] = "383286000000"
    elif fault == "unverified_partial":
        next(fact for fact in evidence["facts"] if fact["reporting_period"]["fiscal_year"] == 2023)["status"] = "provisional"
    elif fault == "unopened_partial":
        del run["citations"]["current"]
    elif fault == "wrong_citation":
        run["citations"]["current"]["text"] += "Unsupported excerpt."
    elif fault == "contradicted_reason":
        result["issues"][0]["detail"] += " FY2022 is absent from the consolidated statement."
    elif fault == "verified_year_gap":
        result["issues"][0].update(role="current", fiscal_year=2023,
                                   detail=result["issues"][0]["detail"].replace("FY2022", "FY2023"))
    repeated = {"status": "matched", **deepcopy(run)}
    if fault == "wrong_replay_result":
        repeated["result"]["issues"] = []
    elif fault == "wrong_replay_citations":
        repeated["citations"]["current"]["http_status"] = 404

    scored = revenue_score.score_case(run, repeated, evidence, label, review, original, sha256(original).hexdigest())
    assert finding in scored["findings"]
    assert not scored["incomplete"] and not scored["end_to_end_complete"]
    if fault in {"wrong_partial_amount", "unverified_partial", "unopened_partial", "wrong_citation"}:
        assert not scored["supported_partial"]


def test_supported_growth_keeps_answer_credit(
    apple_growth: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], bytes],
) -> None:
    run, evidence, label, review, original = apple_growth
    scored = revenue_score.score_case(run, {"status": "matched", **run}, evidence, label, review, original,
                                      sha256(original).hexdigest())
    assert scored["findings"] == []
    assert scored["answer_accurate"] and scored["end_to_end_complete"]
    assert not scored["incomplete"] and not scored["supported_partial"]
