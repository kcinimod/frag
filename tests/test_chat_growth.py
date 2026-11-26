"""Regression coverage for growth questions through the filing chatbot."""

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from test_source_workflow import FIXTURE, success
from test_verification_workflow import ARCHIVE

from frag import cli
from frag.lookup import ask_revenue
from frag.store import SourceStore
from frag.web import create_app

QUESTION = "How did reported consolidated revenue change from FY2022 to FY2023?"
OPENED_CASES = {
    case["case_id"]: case["question"]
    for case in json.loads(
        (Path(__file__).resolve().parents[1] / "artifacts/phase06/fresh-inputs.json").read_bytes()
    )["cases"]
}


def growth_plan(prior: str, current: str) -> dict[str, Any]:
    return {"operation": "growth", "steps": [
        {"operation": "subtract", "inputs": [current, prior]},
        {"operation": "divide", "inputs": ["subtract", prior]},
        {"operation": "to_percent", "inputs": ["divide"]},
    ]}


@pytest.fixture
def microsoft(tmp_path: Path) -> tuple[SourceStore, dict[str, Any]]:
    store = SourceStore(tmp_path / "store")
    source = store.ingest_bytes(gzip.decompress(ARCHIVE.read_bytes()), provenance="local_original")
    return store, source


@pytest.mark.parametrize("question", [QUESTION, OPENED_CASES["P6-02"]])
def test_chat_calculates_growth_with_original_filing_evidence(
    tmp_path: Path, microsoft: tuple[SourceStore, dict[str, Any]], question: str,
) -> None:
    store, source = microsoft
    prior, current = (fact["fact_id"] for fact in source["facts"])
    attempts = []

    def propose(payload: dict[str, Any]) -> str:
        attempts.append(payload)
        return json.dumps(growth_plan(prior, current))

    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}'
    response = client.post(base + "/lookup", json={
        "question": question,
    }, headers={"X-Frag-Ask": "1"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert len(attempts) == 1
    result = response.get_json()
    assert result["status"] == "calculated"
    assert result["percent"] == {"unit": "percent", "value": "6.88"}
    assert result["trace"][0]["result"] == "13645000000"
    assert any("foreign currency" in caveat for caveat in result["scope_caveats"])
    assert len(result["citations"]) == 9
    for role, amount in (("prior", "198,270"), ("current", "211,915")):
        citation = client.get(f"{base}/growth/citations/{role}?prior=2022&current=2023")
        assert citation.mimetype == "text/plain"
        assert amount in citation.text


@pytest.mark.parametrize("question", [
    "What was revenue growth from FY2023 to FY2022?",
    "What was revenue growth between FY2022 and FY2022?",
    "How did revenue change from FY2022?",
    "Revenue from FY2022 to FY2023?",
    "What was revenue guidance growth from FY2022 to FY2023?",
    "What was revenue growth from FY2022 or FY2023 to FY2024 as reported?",
    "What was revenue growth from FY2022 to FY2023 on a constant-currency basis?",
    "What was revenue growth from FY2022 to FY2023 as reported? Use constant currency.",
])
def test_growth_clarifies_ambiguous_requests_before_planning(question: str) -> None:
    def propose(payload: dict[str, Any]) -> str:
        pytest.fail("Ambiguous questions must be resolved before planning.")

    assert ask_revenue({}, question, propose)["status"] == "clarify"


@pytest.mark.parametrize(("case_id", "prior", "current", "equal_length"), [
    ("P6-02", 2022, 2023, {}),
    ("P6-04", 2023, 2024, {}),
    ("P6-06", 2023, 2024, {}),
    ("P6-08", 2024, 2025, {}),
    ("P6-10", 2023, 2024, {}),
    ("P6-12", 2023, 2024, {}),
    ("P6-15", 2022, 2023, {"equal_length": True}),
])
def test_opened_growth_requests_preserve_resolved_years_on_evidence_gap(
    case_id: str, prior: int, current: int, equal_length: dict[str, bool],
) -> None:
    record: dict[str, Any] = {}
    result = ask_revenue(
        {"source_id": "synthetic", "facts": []}, OPENED_CASES[case_id],
        lambda _: pytest.fail("Missing evidence reached the planner"), record=record,
    )
    assert result["status"] == "unavailable"
    assert [issue["fiscal_year"] for issue in result["issues"]] == [prior, current]
    assert record["resolved_request"] == {
        "operation": "growth", "metric": "reported_consolidated_revenue",
        "prior_year": prior, "current_year": current, **equal_length,
    }


@pytest.mark.parametrize(("step", "replacement"), [
    (1, {"operation": "divide", "inputs": ["subtract", "CURRENT"]}),
    (0, {"operation": "subtract", "inputs": ["unknown", "PRIOR"]}),
    (0, {"operation": "multiply", "inputs": ["CURRENT", "PRIOR"]}),
    (0, {"operation": "subtract", "inputs": ["PRIOR", "CURRENT"]}),
    (1, {"operation": "divide", "inputs": ["to_percent", "PRIOR"]}),
    (2, {"operation": "to_percent", "inputs": ["divide", "divide"]}),
])
def test_chat_rejects_plans_that_do_not_match_the_resolved_growth(
    microsoft: tuple[SourceStore, dict[str, Any]], step: int, replacement: dict[str, Any],
) -> None:
    _, source = microsoft
    prior, current = (fact["fact_id"] for fact in source["facts"])
    plan = growth_plan(prior, current)
    plan["steps"][step] = replacement
    proposal = json.dumps(plan).replace("CURRENT", current).replace("PRIOR", prior)
    result = ask_revenue(source, QUESTION, lambda payload: proposal)
    assert result["status"] == "invalid_plan"
    assert "trace" not in result


def test_chat_rejects_unresolved_comparison(microsoft: tuple[SourceStore, dict[str, Any]]) -> None:
    _, source = microsoft
    source["comparison"]["status"] = "unresolved"
    result = ask_revenue(source, QUESTION, lambda payload: pytest.fail("Unresolved comparison reached the planner"))
    assert result["status"] == "unavailable"
    assert result["issues"][0]["code"] == "incompatible"
    assert result["trace"] == []


def test_guidance_and_provisional_revenue_cannot_supply_actuals(tmp_path: Path) -> None:
    store = SourceStore(tmp_path / "store")
    source = store.ingest(FIXTURE.with_name("synthetic_income.html"), provenance="synthetic")
    # Synthetic verified guidance still has the wrong metric.
    source["facts"].append({
        **source["facts"][1], "fact_id": "guidance", "status": "verified", "metric": "revenue_guidance",
    })
    def propose(payload: dict[str, Any]) -> str:
        pytest.fail("Unverified evidence reached the planner")

    result = ask_revenue(source, QUESTION, propose)
    assert result["status"] == "unavailable"
    assert [issue["code"] for issue in result["issues"]] == ["unverified", "unverified"]
    assert result["trace"] == result["citations"] == []


def test_missing_evidence_returns_both_gaps_without_planning() -> None:
    source = {"source_id": "synthetic", "facts": []}
    result = ask_revenue(source, QUESTION, lambda payload: pytest.fail("Missing evidence reached the planner"))
    assert result["status"] == "unavailable"
    assert [issue["fiscal_year"] for issue in result["issues"]] == [2022, 2023]


@pytest.mark.parametrize("question", [
    OPENED_CASES["P6-02"],
    "Revenue growth from fiscal year 2022 to fiscal year 2023.",
    "What was revenue growth between FY2022 and FY2023?",
])
def test_growth_record_replays_through_cli_with_sockets_disabled(
    tmp_path: Path, microsoft: tuple[SourceStore, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], question: str,
) -> None:
    store, source = microsoft
    prior, current = (fact["fact_id"] for fact in source["facts"])
    record = tmp_path / "growth.json"
    monkeypatch.setattr(cli, "propose_lookup", lambda payload: json.dumps(growth_plan(prior, current)))
    assert cli.main(["ask", source["source_id"], question, "--store", str(store.root), "--record", str(record)]) == 0
    result = json.loads(capsys.readouterr().out)
    saved = json.loads(record.read_text(encoding="utf-8"))
    assert saved["resolved_request"] == {
        "operation": "growth", "metric": "reported_consolidated_revenue", "prior_year": 2022, "current_year": 2023,
    }
    assert saved["validation_status"] == "calculated"
    assert result["percent"]["value"] == "6.88"
    assert success("replay-ask", str(record), "--store", str(store.root)) == result
