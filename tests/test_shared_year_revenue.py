"""Exercise the opened P&G and Coca-Cola filings against the Phase 5 scorer review."""

import gzip
import json
import re
import socket
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from test_chat_growth import growth_plan
from test_source_workflow import success

from frag import cli
from frag.store import SourceStore
from frag.web import create_app

ROOT = Path(__file__).resolve().parents[1]
REVIEWS = json.loads((ROOT / "tests/fixtures/phase06_pg_ko_review.json").read_bytes())


def byte_position(original: list[bytes], locator: dict[str, int]) -> int:
    index = locator["line"] - 1
    return (sum(len(line) + 1 for line in original[:index])
            + len(original[index].decode()[:locator["character"] - 1].encode()))


@pytest.mark.parametrize("conflict", ("extra_year_row", "missing_trade_promotion_note"))
def test_shared_row_conflicts_withhold_verified_revenue(conflict: str, tmp_path: Path) -> None:
    filename = "pg-20240630.htm"
    original = gzip.decompress((ROOT / "artifacts/phase06/originals" / (filename + ".gz")).read_bytes())
    review = REVIEWS[filename]["evidence"]
    if conflict == "extra_year_row":
        span = review["locators"]["period_header"]
        start, end = span["start_byte"], span["end_byte"]
        row = next(match[0] for match in re.finditer(rb"<tr[>\s].*?</tr>", original[start:end], re.S)
                   if b"fiscal years ended" in match[0])
        alternate = re.sub(rb"Amounts in millions[^<]+", b"", row, count=1).replace(b"2022", b"2021")
        assert b"fiscal years ended" not in alternate and b"2021" in alternate
        original = original[:end] + alternate + original[end:]
    else:
        span = review["applicable_notes"][2]["locator"]
        original = original[:span["start_byte"]] + original[span["end_byte"]:]
    # Synthetic mutations retain the local-original intake path for verification.
    source = SourceStore(tmp_path).ingest_bytes(original, provenance="local_original")
    assert not any(fact["status"] == "verified" for fact in source["facts"])
    if conflict == "extra_year_row":
        assert not source.get("statement_periods")
    else:
        assert len(source["facts"]) == 3
        assert all("applicable_notes" in fact["unresolved_requirements"] for fact in source["facts"])


@pytest.mark.parametrize("filename", REVIEWS)
def test_shared_year_ingest_matches_reviewed_observations(filename: str, tmp_path: Path) -> None:
    reference = REVIEWS[filename]
    reviewed = reference["evidence"]
    original = gzip.decompress((ROOT / "artifacts/phase06/originals" / (filename + ".gz")).read_bytes())
    store = SourceStore(tmp_path)
    source = store.ingest_bytes(original, provenance="local_original")
    assert source["source_hash"] == reference["source"]["sha256"]
    facts = {str(fact["reporting_period"]["fiscal_year"]): fact for fact in source["facts"]}
    assert facts.keys() == reviewed["facts"].keys(), source["diagnostics"]
    lines = original.split(b"\n")
    for year, fact in facts.items():
        expected = reviewed["facts"][year]
        assert fact["status"] == "verified", (fact["unresolved_requirements"], source["diagnostics"])
        assert fact["metric_label"] == reviewed["statement_row"]
        for field in ("raw_amount", "normalized_amount", "currency", "scale", "scope"):
            assert fact[field] == expected[field]
        assert fact["reporting_period"] == {
            "kind": "annual", "fiscal_year": int(year),
            "start": expected["period_start"], "end": expected["period_end"],
        }
        assert fact["inline_xbrl"]["fact_element_id"] == expected["element_id"]
        assert fact["inline_xbrl"]["context_id"] == expected["context_id"]
        assert fact["inline_xbrl"]["concept"] == expected["concept"]
        for key, span in {
            "table": reviewed["locators"]["statement"],
            "statement_heading": reviewed["locators"]["statement_title_and_units"],
            "annual_header": reviewed["locators"]["period_header"],
            "year_header": reviewed["locators"]["period_header"],
            "unit_header": reviewed["locators"]["statement_title_and_units"],
            "value": expected["locators"]["statement_cell"],
            "inline_fact": expected["locators"]["inline_fact"],
            "inline_context": expected["locators"]["context"],
            "currency_measure": expected["locators"]["unit"],
        }.items():
            assert span["start_byte"] <= byte_position(lines, fact["locators"][key]) < span["end_byte"], key
    again = store.ingest_bytes(original, provenance="local_original")
    assert again["facts"] == source["facts"]
    assert store.inspect()["source_count"] == 1


@pytest.mark.parametrize("filename", REVIEWS)
def test_shared_year_answers_and_replay_reopen_reviewed_citations_offline(
    filename: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def deny_network(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Offline filing workflow opened a socket")

    monkeypatch.setattr(socket, "socket", deny_network)
    reference = REVIEWS[filename]
    original = gzip.decompress((ROOT / "artifacts/phase06/originals" / (filename + ".gz")).read_bytes())
    lines = original.split(b"\n")
    path = tmp_path / filename
    path.write_bytes(original)
    store = SourceStore(tmp_path / "store")
    source = success("ingest", str(path), "--provenance", "local_original", "--store", str(store.root))
    path.unlink()
    facts = {fact["reporting_period"]["fiscal_year"]: fact for fact in source["facts"]}

    def propose(payload: dict[str, Any]) -> str:
        if "Use these exact inputs in the growth plan" in payload["messages"][1]["content"]:
            return json.dumps(growth_plan(facts[2023]["fact_id"], facts[2024]["fact_id"]))
        return json.dumps({"operation": "lookup", "fact_id": facts[2024]["fact_id"]})

    client = create_app(store, tmp_path, planner=propose).test_client()
    monkeypatch.setattr(cli, "propose_lookup", propose)
    base = f'/api/sources/{source["source_id"]}'
    for case in reference["cases"]:
        question = case["question"]
        response = client.post(base + "/lookup", json={"question": question}, headers={"X-Frag-Ask": "1"})
        assert response.status_code == 200
        result = response.get_json()
        if case["kind"] == "lookup":
            assert result["status"] == "answered", result
            assert result["fact"]["normalized_amount"] == reference["evidence"]["facts"]["2024"]["normalized_amount"]
            amounts = {"revenue": reference["evidence"]["facts"]["2024"]["raw_amount"]}
        else:
            assert result["status"] == "calculated", result
            assert result["percent"] == {"unit": "percent", "value": case["percent"]}
            assert [step["operation"] for step in result["trace"]] == ["subtract", "divide", "to_percent"]
            assert result["trace"][0]["result"] == case["absolute_change"]
            amounts = {role: reference["evidence"]["facts"][year]["raw_amount"]
                       for role, year in (("prior", "2023"), ("current", "2024"))}
            if reference["evidence"]["statement_row"] == "Net Operating Revenues":
                assert any("refranchising" in caveat for caveat in result["scope_caveats"])

        excerpts = {}
        note_spans = []
        for citation in result["citations"]:
            key = citation["id"]
            route = (f"/lookup/citations/2024/{key}" if case["kind"] == "lookup"
                     else f"/growth/citations/{key}?prior=2023&current=2024")
            excerpt = client.get(base + route)
            assert excerpt.status_code == 200
            assert source["source_hash"] in excerpt.text
            excerpts[key] = excerpt.text
            if "start" in citation["locator"]:
                note_spans.append(tuple(byte_position(lines, citation["locator"][edge])
                                        for edge in ("start", "end_exclusive")))
        for role, amount in amounts.items():
            for text in (amount, reference["evidence"]["statement_row"], "in millions", "iso4217:USD",
                         "2023" if role == "prior" else "2024"):
                assert text.casefold() in excerpts[role].casefold()
        for note in reference["evidence"]["applicable_notes"]:
            span = note["locator"]
            start, end = span["start_byte"], span["end_byte"]
            assert sha256(original[start:end]).hexdigest() == span["sha256"]
            assert any(a <= start < end <= b for a, b in note_spans), note["label"]

        saved = tmp_path / f"{case['kind']}.json"
        assert cli.main(["ask", source["source_id"], question, "--store", str(store.root),
                         "--record", str(saved)]) == 0
        assert json.loads(capsys.readouterr().out) == result
        assert success("replay-ask", str(saved), "--store", str(store.root)) == result
