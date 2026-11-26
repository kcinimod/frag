"""Check Netflix against the independent Phase 6 custody review."""

import gzip
import json
import socket
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from test_chat_growth import growth_plan
from test_shared_year_revenue import byte_position
from test_source_workflow import success

from frag import cli
from frag.store import SourceStore
from frag.web import create_app

ROOT = Path(__file__).resolve().parents[1]
REVIEW = json.loads((ROOT / "tests/fixtures/phase06_netflix_review.json").read_bytes())


@pytest.fixture
def original() -> bytes:
    archive = ROOT / "artifacts/phase06/originals/nflx-20241231.htm.gz"
    return gzip.decompress(archive.read_bytes())


def test_netflix_verifies_all_reviewed_statement_periods(original: bytes, tmp_path: Path) -> None:
    store = SourceStore(tmp_path)
    source = store.ingest_bytes(original, provenance="local_original")
    assert source["source_hash"] == REVIEW["source"]["sha256"]
    evidence = REVIEW["evidence"]
    facts = {str(fact["reporting_period"]["fiscal_year"]): fact for fact in source["facts"]}
    assert facts.keys() == evidence["facts"].keys()
    lines = original.split(b"\n")
    for year, fact in facts.items():
        expected = evidence["facts"][year]
        assert fact["status"] == "verified", fact["unresolved_requirements"]
        assert fact["metric_label"] == evidence["statement_row"]
        for field in ("raw_amount", "normalized_amount", "currency", "scale", "scope"):
            assert fact[field] == expected[field]
        assert fact["reporting_period"] == {
            "kind": "annual", "fiscal_year": int(year),
            "start": expected["period_start"], "end": expected["period_end"],
        }
        for actual_key, expected_key in (
            ("fact_element_id", "element_id"), ("context_id", "context_id"), ("concept", "concept"),
        ):
            assert fact["inline_xbrl"][actual_key] == expected[expected_key]
        for locator, span in {
            "table": evidence["locators"]["statement"],
            "metric_label": evidence["locators"]["revenue_row"],
            "annual_header": evidence["locators"]["period_header"],
            "unit_header": evidence["locators"]["statement_title_and_units"],
            "year_header": expected["locators"]["period_cell"],
            "value": expected["locators"]["statement_cell"],
            "inline_fact": expected["locators"]["inline_fact"],
            "inline_context": expected["locators"]["context"],
            "currency_measure": expected["locators"]["unit"],
        }.items():
            start, end = span["start_byte"], span["end_byte"]
            assert sha256(original[start:end]).hexdigest() == span["sha256"]
            assert start <= byte_position(lines, fact["locators"][locator]) < end
        # The heading anchor starts at the enclosing div, before the reviewed text.
        heading = byte_position(lines, fact["locators"]["statement_heading"])
        title = evidence["locators"]["statement_title_and_units"]["start_byte"]
        heading_end = original.index(b"</div>", heading)
        assert heading <= title < heading_end
        assert b"CONSOLIDATED STATEMENTS OF OPERATIONS" in original[heading:heading_end]
        for note_id, note in zip(
            ("note-1-consolidation", "note-1-revenue"), evidence["applicable_notes"], strict=True,
        ):
            locator = next(item["locator"] for item in fact["applicable_notes"] if item["id"] == note_id)
            span = note["locator"]
            start, end = span["start_byte"], span["end_byte"]
            assert sha256(original[start:end]).hexdigest() == span["sha256"]
            assert byte_position(lines, locator["start"]) <= start < end <= byte_position(
                lines, locator["end_exclusive"],
            )


def test_netflix_incomplete_revenue_policy_keeps_observations_provisional(original: bytes, tmp_path: Path) -> None:
    # Synthetic control removes support from the continuation after the page break.
    sentence = b"are collected from members and remitted to governmental authorities."
    assert original.count(sentence) == 1
    changed = original.replace(sentence, b"are collected from members.")
    source = SourceStore(tmp_path).ingest_bytes(changed, provenance="local_original")
    assert len(source["facts"]) == 3
    assert all(fact["status"] == "provisional" and "applicable_notes" in fact["unresolved_requirements"]
               for fact in source["facts"])
    assert set(source["statement_periods"]["period_headers"]) == REVIEW["evidence"]["facts"].keys()


@pytest.mark.parametrize("case", REVIEW["cases"], ids=[case["case_id"] for case in REVIEW["cases"]])
def test_netflix_answers_and_citations_replay_offline(
    case: dict[str, Any], original: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def deny_network(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Offline filing workflow opened a socket")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, deny_network)
    path = tmp_path / REVIEW["source"]["original_filename"]
    path.write_bytes(original)
    store = SourceStore(tmp_path / "store")
    source = success("ingest", str(path), "--provenance", "local_original", "--store", str(store.root))
    path.unlink()
    facts = {fact["reporting_period"]["fiscal_year"]: fact for fact in source["facts"]}

    def propose(_: dict[str, Any]) -> str:
        if case["outcome"] == "absent_year":
            pytest.fail("A missing year should be resolved before planning")
        if case["kind"] == "lookup":
            return json.dumps({"operation": "lookup", "fact_id": facts[2024]["fact_id"]})
        return json.dumps(growth_plan(facts[2023]["fact_id"], facts[2024]["fact_id"]))

    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}'
    response = client.post(base + "/lookup", json={"question": case["question"]}, headers={"X-Frag-Ask": "1"})
    assert response.status_code == 200
    result = response.get_json()
    reviewed_facts = REVIEW["evidence"]["facts"]
    if case["kind"] == "lookup":
        assert result["status"] == "answered", result
        assert result["fact"]["normalized_amount"] == reviewed_facts["2024"]["normalized_amount"]
        routes = "/lookup/citations/2024/{key}"
        operands = {"revenue": 2024}
    else:
        prior, current = case["years"]
        routes = f"/growth/citations/{{key}}?prior={prior}&current={current}"
        operands = {"current": current}
        if case["outcome"] == "absent_year":
            assert result["status"] == "unavailable" and result["percent"] is None and not result["trace"]
            assert [(issue["code"], issue["fiscal_year"]) for issue in result["issues"]] == [("absent", prior)]
            assert [(fact["role"], fact["normalized_amount"]) for fact in result["operands"]] == [
                ("current", reviewed_facts["2024"]["normalized_amount"]),
            ]
        else:
            operands["prior"] = prior
            assert result["status"] == "calculated", result
            assert result["percent"] == {"unit": "percent", "value": case["percent"]}
            assert [step["operation"] for step in result["trace"]] == ["subtract", "divide", "to_percent"]
            assert result["trace"][0]["result"] == case["absolute_change"]

    excerpts = {}
    for citation in result["citations"]:
        key = citation["id"]
        excerpt = client.get(base + routes.format(key=key))
        assert excerpt.status_code == 200
        assert source["source_hash"] in excerpt.text
        excerpts[key] = excerpt.text.partition("\n\n")[2]
    for role, year in operands.items():
        expected = reviewed_facts[str(year)]
        for text in (expected["raw_amount"], f"Year ended December 31,\n{year}", "iso4217:USD",
                     "in thousands", "Revenues"):
            assert text.casefold() in excerpts[role].casefold()
    assert "Intercompany balances and transactions have been eliminated" in excerpts["note-1-consolidation"]
    assert "recognized ratably over each monthly membership period" in excerpts["note-1-revenue"]
    assert "remitted to governmental authorities" in excerpts["note-1-revenue"]
    if case["outcome"] == "absent_year":
        header = excerpts["statement-periods"].splitlines()
        assert any("December 31" in line for line in header)
        assert {line.strip() for line in header if line.strip().isdecimal()} == reviewed_facts.keys()

    monkeypatch.setattr(cli, "propose_lookup", propose)
    record = tmp_path / "ask.json"
    assert cli.main(["ask", source["source_id"], case["question"], "--store", str(store.root),
                     "--record", str(record)]) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert success("replay-ask", str(record), "--store", str(store.root)) == result
