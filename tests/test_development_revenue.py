"""Development filing regression through ingestion, question and citation workflows."""

import gzip
import json
import socket
from pathlib import Path
from typing import Any

import pytest
from test_source_workflow import success

from frag.lookup import ask_revenue
from frag.store import SourceStore
from frag.web import create_app

ARCHIVE = Path(__file__).parents[1] / "artifacts/phase04/development/originals/aapl-20230930.htm.gz"


@pytest.mark.parametrize(("year", "start", "end", "raw", "amount", "element", "character"), [
    (2021, "2020-09-27", "2021-09-25", "365,817", "365817000000", "f-71", 500452),
    (2022, "2021-09-26", "2022-09-24", "394,328", "394328000000", "f-70", 499783),
    (2023, "2022-09-25", "2023-09-30", "383,285", "383285000000", "f-69", 499115),
])
def test_apple_lookup_opens_the_original_dated_statement_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    year: int, start: str, end: str, raw: str, amount: str, element: str, character: int,
) -> None:
    def deny_network(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Offline verification opened a socket")

    monkeypatch.setattr(socket, "socket", deny_network)
    original = gzip.decompress(ARCHIVE.read_bytes())
    path = tmp_path / "apple.html"
    path.write_bytes(original)
    store = SourceStore(tmp_path / "store")
    source = store.ingest(path, provenance="local_original")
    assert store.ingest(path, provenance="local_original") == source
    path.unlink()
    assert store.inspect()["source_count"] == 1

    def propose(payload: dict[str, Any]) -> str:
        prompt = json.loads(payload["messages"][1]["content"])
        fact, = prompt["evidence"]
        assert fact["reporting_period"]["fiscal_year"] == year
        return json.dumps({"operation": "lookup", "fact_id": fact["fact_id"]})

    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}/lookup'
    response = client.post(base, json={"question": f"What was revenue in FY{year}?"},
                           headers={"X-Frag-Ask": "1"})
    result = response.get_json()
    assert result["status"] == "answered"
    fact = result["fact"]
    assert fact["company"] == "Apple Inc."
    assert fact["reporting_period"] == {"kind": "annual", "fiscal_year": year, "start": start, "end": end}
    assert (fact["raw_amount"], fact["normalized_amount"]) == (raw, amount)
    assert (fact["currency"], fact["scale"], fact["scope"]) == ("USD", 1_000_000, "consolidated")
    assert fact["inline_xbrl"]["fact_element_id"] == element
    assert fact["locators"]["value"]["character"] == character
    assert [note["number"] for note in fact["applicable_notes"]] == [1, 2, 13]
    assert result["source_hash"] == "bda1f34435199672c16ecdf2034c650872d2cac8399ed0d179fc25450b080b90"
    assert Path(source["original_path"]).read_bytes() == original
    citation = client.get(f"{base}/citations/{year}/revenue")
    assert citation.status_code == 200
    excerpt = " ".join(citation.text.split())
    assert all(text in excerpt for text in (
        "CONSOLIDATED STATEMENTS OF OPERATIONS", "Total net sales", "In millions",
        f"September {int(end[-2:])}, {year}", raw, result["source_hash"],
    ))
    assert f"HTML line 4, character {fact['locators']['value']['character']}" in citation.text
    for number, phrase in [(1, "2023 spanned 53 weeks"), (2, "control of the products or services"),
                           (13, "Net sales for geographic segments")]:
        note = client.get(f"{base}/citations/{year}/note-{number}")
        assert note.status_code == 200
        assert phrase in note.text
    assert [item["id"] for item in result["citations"]] == ["revenue", "note-1", "note-2", "note-13"]


@pytest.mark.parametrize(("before", "after", "gap"), [
    (b'contextRef="c-1" decimals="-6" name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"'
     b' format="ixt:num-dot-decimal" scale="6" id="f-69"',
     b'contextRef="c-20" decimals="-6" name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"'
     b' format="ixt:num-dot-decimal" scale="6" id="f-69"', "displayed fiscal year-end"),
    (b'contextRef="c-1" decimals="-6" name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"'
     b' format="ixt:num-dot-decimal" scale="6" id="f-69"',
     b'contextRef="c-14" decimals="-6" name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"'
     b' format="ixt:num-dot-decimal" scale="6" id="f-69"', "dimensions that conflict with consolidated scope"),
    (b'<xbrli:unit id="usd"><xbrli:measure>iso4217:USD',
     b'<xbrli:unit id="usd"><xbrli:measure>iso4217:CAD', "visible statement currency"),
    (b'format="ixt:num-dot-decimal" scale="6" id="f-69"',
     b'format="ixt:num-dot-decimal" scale="3" id="f-69"', "visible statement scale"),
    (b'383,285</ix:nonFraction>&#160;</span>', b'383,285</ix:nonFraction>8&#160;</span>',
     "displayed revenue amount"),
    (b"Basis of Presentation and Preparation", b"Basis of Presentation and Reporting",
     "note_1_boundary_or_content"),
])
def test_synthetic_disagreement_returns_a_specific_lookup_gap(
    tmp_path: Path, before: bytes, after: bytes, gap: str,
) -> None:
    original = gzip.decompress(ARCHIVE.read_bytes())
    assert before in original
    store = SourceStore(tmp_path / "store")
    source = store.ingest_bytes(original.replace(before, after, 1), provenance="synthetic")
    assert all(fact["status"] == "provisional" for fact in source["facts"])

    def propose(payload: dict[str, Any]) -> str:
        pytest.fail("An unsupported dated lookup reached the planner")

    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}/lookup'
    response = client.post(base, json={"question": "What was FY2023 revenue?"},
                           headers={"X-Frag-Ask": "1"})
    assert response.status_code == 200
    result = response.get_json()
    assert result["status"] == "evidence_unavailable"
    assert gap in result["message"]
    assert client.get(base + "/citations/2023/revenue").status_code == 404


@pytest.mark.parametrize("provenance", ["local_original", "synthetic"])
def test_saved_development_lookup_and_evidence_gap_replay_offline(tmp_path: Path, provenance: str) -> None:
    path = tmp_path / "apple.html"
    path.write_bytes(gzip.decompress(ARCHIVE.read_bytes()))
    store = str(tmp_path / "store")
    source = success("ingest", str(path), "--provenance", provenance, "--store", store)
    path.unlink()
    record: dict[str, Any] = {}

    def propose(payload: dict[str, Any]) -> str:
        assert provenance == "local_original"
        prompt = json.loads(payload["messages"][1]["content"])
        return json.dumps({"operation": "lookup", "fact_id": prompt["evidence"][-1]["fact_id"]})

    result = ask_revenue(source, "What was FY2023 revenue?", propose, record=record)
    expected = "answered" if provenance == "local_original" else "evidence_unavailable"
    assert result["status"] == expected
    if provenance == "synthetic":
        assert record["model_request"] is record["proposed_plan"] is record["timings_ms"]["model"] is None
        assert record["timings_ms"]["validation_and_execution"] is not None
    saved = tmp_path / "lookup.json"
    saved.write_text(json.dumps(record), encoding="utf-8")
    assert success("replay-lookup", str(saved), "--store", store) == result
