"""Check the remaining opened filings against the independent Phase 5 review."""

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
REVIEWS = json.loads((ROOT / "tests/fixtures/phase06_ge_hd_ups_review.json").read_bytes())


def test_home_depot_newer_observations_survive_missing_oldest_week_count(tmp_path: Path) -> None:
    original = gzip.decompress((ROOT / "artifacts/phase06/originals/hd-20250202.htm.gz").read_bytes())
    # Synthetic mutation removes one disclosed length while preserving the fiscal calendar rule.
    phrase = b"fiscal 2023 and fiscal 2022 include 52 weeks"
    assert phrase in original
    changed = original.replace(phrase, b"fiscal 2023 includes 52 weeks", 1)
    source = SourceStore(tmp_path).ingest_bytes(changed, provenance="local_original")
    facts = {fact["reporting_period"]["fiscal_year"]: fact for fact in source["facts"]}
    assert facts[2023]["status"] == facts[2024]["status"] == "verified"
    assert facts[2022]["status"] == "provisional"
    assert "fiscal_calendar_verification" in facts[2022]["unresolved_requirements"]


def test_embedded_statement_consolidation_policy_matches_the_cover_issuer(tmp_path: Path) -> None:
    original = gzip.decompress((ROOT / "artifacts/phase06/originals/ge-20241231.htm.gz").read_bytes())
    span = REVIEWS["ge-20241231.htm"]["evidence"]["applicable_notes"][1]["locator"]
    start, end = span["start_byte"], span["end_byte"]
    paragraph = original[start:end]
    issuer = b"General Electric Company"
    assert issuer in paragraph
    # Synthetic mutation changes the issuer's name in the scope disclosure only.
    changed = original[:start] + paragraph.replace(issuer, b"Different Company", 1) + original[end:]
    source = SourceStore(tmp_path).ingest_bytes(changed, provenance="local_original")
    assert len(source["facts"]) == 3
    assert all(fact["status"] == "provisional" and
               "statement_issuer_verification" in fact["unresolved_requirements"] for fact in source["facts"])
    assert not source.get("statement_periods")


@pytest.mark.parametrize("filename", ("hd-20250202.htm", "ups-20241231.htm"))
def test_unresolved_transaction_disclosure_preserves_earlier_verified_lookup(filename: str, tmp_path: Path) -> None:
    original = gzip.decompress((ROOT / "artifacts/phase06/originals" / (filename + ".gz")).read_bytes())
    span = REVIEWS[filename]["evidence"]["applicable_notes"][-1]["locator"]
    # Synthetic mutation leaves the transaction note section but removes the supporting paragraph.
    changed = original[:span["start_byte"]] + original[span["end_byte"]:]
    source = SourceStore(tmp_path).ingest_bytes(changed, provenance="local_original")
    facts = {fact["reporting_period"]["fiscal_year"]: fact for fact in source["facts"]}
    assert facts[2023]["status"] == "verified"
    assert facts[2024]["status"] == "provisional"
    assert "applicable_notes" in facts[2024]["unresolved_requirements"]


@pytest.mark.parametrize("filename", REVIEWS)
def test_opened_filing_matches_reviewed_statement_observations(filename: str, tmp_path: Path) -> None:
    reference = REVIEWS[filename]
    reviewed = reference["evidence"]
    original = gzip.decompress((ROOT / "artifacts/phase06/originals" / (filename + ".gz")).read_bytes())
    source = SourceStore(tmp_path).ingest_bytes(original, provenance="local_original")
    assert source["source_hash"] == reference["source"]["sha256"]
    facts = {str(fact["reporting_period"]["fiscal_year"]): fact for fact in source["facts"]}
    expected_facts = reviewed["facts"]
    provisional = reviewed.get("provisional_observation")
    if provisional:
        expected_facts = {str(provisional["fiscal_year"]): provisional}
    else:
        assert facts.keys() == expected_facts.keys(), source["diagnostics"]
    lines = original.split(b"\n")
    for year, expected in expected_facts.items():
        assert year in facts, source["diagnostics"]
        fact = facts[year]
        assert fact["status"] == ("provisional" if provisional else "verified"), source["diagnostics"]
        assert fact["metric_label"] == reviewed["statement_row"]
        for field in ("raw_amount", "normalized_amount", "currency", "scale", "scope"):
            assert fact[field] == expected[field]
        assert fact["reporting_period"] == {
            "kind": "annual", "fiscal_year": int(year),
            "start": expected["period_start"], "end": expected["period_end"],
        }
        spans = {
            "table": reviewed["locators"]["statement"],
            "annual_header": reviewed["locators"]["period_header"],
            "year_header": reviewed["locators"]["period_header"],
            "unit_header": reviewed["locators"]["statement_title_and_units"],
            "value": expected["locators"]["statement_cell"],
        }
        if provisional:
            assert "inline_xbrl_verification" in fact["unresolved_requirements"]
        else:
            assert fact["inline_xbrl"]["fact_element_id"] == expected["element_id"]
            assert fact["inline_xbrl"]["context_id"] == expected["context_id"]
            assert fact["inline_xbrl"]["concept"] == expected["concept"]
            spans.update(inline_fact=expected["locators"]["inline_fact"],
                         inline_context=expected["locators"]["context"],
                         currency_measure=expected["locators"]["unit"])
        for key, span in spans.items():
            assert span["start_byte"] <= byte_position(lines, fact["locators"][key]) < span["end_byte"], key


@pytest.mark.parametrize("filename", REVIEWS)
def test_opened_filing_answers_and_citations_replay_offline(
    filename: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def deny_network(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Offline workflow opened a socket")

    monkeypatch.setattr(socket, "socket", deny_network)
    reference = REVIEWS[filename]
    original = gzip.decompress((ROOT / "artifacts/phase06/originals" / (filename + ".gz")).read_bytes())
    lines = original.split(b"\n")
    store = SourceStore(tmp_path)
    source = store.ingest_bytes(original, provenance="local_original")
    facts = {fact["reporting_period"]["fiscal_year"]: fact for fact in source["facts"]}

    def propose(payload: dict[str, Any]) -> str:
        if "Use these exact inputs in the growth plan" in payload["messages"][1]["content"]:
            return json.dumps(growth_plan(facts[2023]["fact_id"], facts[2024]["fact_id"]))
        assert 2024 in facts and facts[2024]["status"] == "verified"
        return json.dumps({"operation": "lookup", "fact_id": facts[2024]["fact_id"]})

    monkeypatch.setattr(cli, "propose_lookup", propose)
    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}'
    for case in reference["cases"]:
        question = case["question"]
        response = client.post(base + "/lookup", json={"question": question}, headers={"X-Frag-Ask": "1"})
        assert response.status_code == 200
        result = response.get_json()
        kind, outcome = case["kind"], case["outcome"]
        if outcome == "present_unverifiable":
            assert result["status"] == "evidence_unavailable"
            assert result["fiscal_year"] == 2018 and result["reason"] == "unverified"
            assert "inline XBRL" in result["message"]
            assert "fact" not in result and "121,615" not in result["message"]
        elif outcome == "incompatible_periods":
            assert result["status"] == "unavailable" and result["percent"] is None and result["trace"] == []
            assert "FY2023 spans 52 weeks and FY2024 spans 53 weeks" in result["issues"][0]["detail"]
            assert [fact["reporting_period"]["fiscal_year"] for fact in result["operands"]] == [2023, 2024]
        elif kind == "lookup":
            assert result["status"] == "answered", result
            assert result["fact"]["normalized_amount"] == reference["evidence"]["facts"]["2024"]["normalized_amount"]
        else:
            assert result["status"] == "calculated", result
            assert result["percent"] == {"unit": "percent", "value": case["percent"]}
            assert [step["operation"] for step in result["trace"]] == ["subtract", "divide", "to_percent"]
            assert result["trace"][0]["result"] == case["absolute_change"]
            for phrase in {
                "ge-20241231.htm": ["continuing-operations", "discontinued operations"],
                "hd-20250202.htm": ["52 weeks", "53 weeks", "SRS"],
                "ups-20241231.htm": ["Coyote"],
            }[filename]:
                assert phrase in " ".join(result["scope_caveats"])

        note_spans = []
        for citation in result["citations"]:
            key = citation["id"]
            route = (f"/lookup/citations/2024/{key}" if kind == "lookup"
                     else f"/growth/citations/{key}?prior=2023&current=2024")
            excerpt = client.get(base + route)
            assert excerpt.status_code == 200 and source["source_hash"] in excerpt.text
            if key in {"revenue", "prior", "current"}:
                year = "2023" if key == "prior" else "2024"
                expected = reference["evidence"]["facts"][year]
                for text in (year, expected["raw_amount"], "in millions", "iso4217:USD"):
                    assert text.casefold() in excerpt.text.casefold()
            else:
                note_spans.append(tuple(byte_position(lines, citation["locator"][edge])
                                        for edge in ("start", "end_exclusive")))
        if outcome != "present_unverifiable":
            for note in reference["evidence"]["applicable_notes"]:
                span = note["locator"]
                start, end = span["start_byte"], span["end_byte"]
                assert sha256(original[start:end]).hexdigest() == span["sha256"]
                assert any(a <= start < end <= b for a, b in note_spans), note["label"]

        saved = tmp_path / f'{case["case_id"]}.json'
        assert cli.main(["ask", source["source_id"], question, "--store", str(store.root),
                         "--record", str(saved)]) == 0
        assert json.loads(capsys.readouterr().out) == result
        assert success("replay-ask", str(saved), "--store", str(store.root)) == result
