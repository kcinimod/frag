"""Exercise the filing-scoped chatbot through the local browser API."""

import gzip
import json
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from test_source_workflow import FIXTURE, success
from test_verification_workflow import ARCHIVE

from frag import cli
from frag.local_model import ModelUnavailable
from frag.store import SourceStore
from frag.web import create_app


def test_lookup_answers_with_original_filing_citation(tmp_path: Path) -> None:
    store = SourceStore(tmp_path / "store")
    source = store.ingest_bytes(gzip.decompress(ARCHIVE.read_bytes()), provenance="local_original")
    fact_id = source["facts"][1]["fact_id"]
    attempts: list[dict[str, Any]] = []

    def propose(payload: dict[str, Any]) -> str:
        attempts.append(payload)
        return json.dumps({"operation": "lookup", "fact_id": fact_id})

    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}/lookup'
    response = client.post(
        base, json={"question": "What was reported consolidated revenue in FY2023?"},
        headers={"X-Frag-Ask": "1"},
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    result = response.get_json()
    assert len(attempts) == 1
    assert result["status"] == "answered"
    assert result["fact"]["normalized_amount"] == "211915000000"
    assert result["fact"]["currency"] == "USD"
    assert result["fact"]["fact_id"] == fact_id
    assert result["source_hash"] == source["source_hash"]
    citation = client.get(base + "/citations/2023/revenue")
    assert citation.mimetype == "text/plain"
    assert citation.text.endswith("Total revenue\n2023\n(In millions, except per share amounts)\n211,915\n")


@pytest.mark.parametrize("question", [
    "What was revenue?",
    "Revenue in FY2022 or FY2023?",
    "What is revenue guidance for FY2023?",
    "What was FY2023 revenue growth?",
    "Revenue for Microsoft FY2023",
])
def test_ambiguous_or_unsupported_question_clarifies_without_model(tmp_path: Path, question: str) -> None:
    store = SourceStore(tmp_path / "store")
    source = store.ingest_bytes(gzip.decompress(ARCHIVE.read_bytes()), provenance="local_original")

    def propose(payload: dict[str, Any]) -> str:
        pytest.fail("An unsupported question should never reach the planner.")

    client = create_app(store, tmp_path, planner=propose).test_client()
    response = client.post(
        f'/api/sources/{source["source_id"]}/lookup',
        json={"question": question}, headers={"X-Frag-Ask": "1"},
    )
    assert response.get_json()["status"] == "clarify"


@pytest.mark.parametrize(("proposal", "status"), [
    ("wrong_year", "invalid_plan"),
    ('{"operation": "lookup", "fact_id": "unknown"}', "invalid_plan"),
    ('{"operation": "growth", "fact_id": "CORRECT_ID"}', "invalid_plan"),
    ('{"operation": "lookup", "operation": "lookup", "fact_id": "CORRECT_ID"}', "invalid_plan"),
    (TimeoutError(), "model_timeout"),
    (ModelUnavailable(), "model_unavailable"),
])
def test_one_attempt_and_distinct_lookup_failures(tmp_path: Path, proposal: str | Exception, status: str) -> None:
    store = SourceStore(tmp_path / "store")
    source = store.ingest_bytes(gzip.decompress(ARCHIVE.read_bytes()), provenance="local_original")
    attempts = 0

    def propose(payload: dict[str, Any]) -> str:
        nonlocal attempts
        attempts += 1
        if isinstance(proposal, Exception):
            raise proposal
        if proposal == "wrong_year":
            return json.dumps({"operation": "lookup", "fact_id": source["facts"][0]["fact_id"]})
        return proposal.replace("CORRECT_ID", source["facts"][1]["fact_id"])

    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}'
    response = client.post(
        base + "/lookup", json={"question": "Revenue for fiscal year 2023"},
        headers={"X-Frag-Ask": "1"},
    )
    assert response.get_json()["status"] == status
    assert attempts == 1
    growth = client.get(base + "/growth?prior=2022&current=2023")
    assert growth.get_json()["percent"]["value"] == "6.88"


@pytest.mark.parametrize("valid_shape", [True, False])
def test_provisional_synthetic_revenue_never_reaches_the_planner_as_evidence(
    tmp_path: Path, valid_shape: bool,
) -> None:
    store = SourceStore(tmp_path / "store")
    source = store.ingest(FIXTURE.with_name("synthetic_income.html"), provenance="synthetic")
    fact_id = source["facts"][1]["fact_id"]

    def propose(payload: dict[str, Any]) -> str:
        assert json.loads(payload["messages"][1]["content"])["evidence"] == []
        return json.dumps({"operation": "lookup", "fact_id": fact_id}) if valid_shape else "{"

    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}/lookup'
    response = client.post(
        base, json={"question": "What was FY2023 revenue?"}, headers={"X-Frag-Ask": "1"},
    )
    assert response.get_json()["status"] == ("evidence_unavailable" if valid_shape else "invalid_plan")
    assert client.get(base + "/citations/2023/revenue").status_code == 404


def test_explicit_cli_record_replays_with_model_unloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    store = SourceStore(tmp_path / "store")
    source = store.ingest_bytes(gzip.decompress(ARCHIVE.read_bytes()), provenance="local_original")
    record = tmp_path / "lookup.json"
    question = "FY2022 total revenue"

    def propose(payload: dict[str, Any]) -> str:
        return json.dumps({"operation": "lookup", "fact_id": source["facts"][0]["fact_id"]})

    monkeypatch.setattr(cli, "propose_lookup", propose)
    monkeypatch.setattr("sys.stdin", StringIO(question + "\n"))
    assert cli.main(["ask", source["source_id"], "--store", str(store.root), "--record", str(record)]) == 0
    result = json.loads(capsys.readouterr().out)
    saved = json.loads(record.read_text(encoding="utf-8"))
    assert saved["question"] == question
    assert saved["resolved_request"]["fiscal_year"] == 2022
    assert saved["source"]["source_hash"] == source["source_hash"]
    assert saved["evidence"] == json.loads(saved["model_request"]["messages"][1]["content"])["evidence"]
    assert saved["validation_status"] == "answered"
    assert result["fact"]["normalized_amount"] == "198270000000"

    assert success("replay-lookup", str(record), "--store", str(store.root)) == result
