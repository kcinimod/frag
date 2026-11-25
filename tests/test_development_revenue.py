"""Development filing regression through ingestion, question and citation workflows."""

import gzip
import json
import socket
from pathlib import Path
from typing import Any

import pytest
from test_chat_growth import QUESTION, growth_plan
from test_source_workflow import success

from frag.lookup import ask_revenue
from frag.store import SourceStore
from frag.web import create_app

ARCHIVE = Path(__file__).parents[1] / "artifacts/phase04/development/originals/aapl-20230930.htm.gz"
LEGACY_REPLAYS = Path(__file__).parent / "fixtures/legacy_apple_replays.json.gz"


def test_apple_growth_question_opens_both_original_cells_and_replays(tmp_path: Path) -> None:
    store = SourceStore(tmp_path / "store")
    source = store.ingest_bytes(gzip.decompress(ARCHIVE.read_bytes()), provenance="local_original")

    def propose(payload: dict[str, Any]) -> str:
        evidence = json.loads(payload["messages"][1]["content"].splitlines()[0])["evidence"]
        by_year = {fact["reporting_period"]["fiscal_year"]: fact["fact_id"] for fact in evidence}
        assert list(by_year) == [2023, 2022]
        return json.dumps(growth_plan(by_year[2022], by_year[2023]))

    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}'
    result = client.post(base + "/lookup", json={"question": QUESTION}, headers={"X-Frag-Ask": "1"}).get_json()
    assert result["status"] == "calculated"
    assert result["percent"] == {"unit": "percent", "value": "-2.80"}
    assert [step["result"] for step in result["trace"]] == ["-11043000000", "-11043/394328", "-2.80"]
    assert [(fact["role"], fact["normalized_amount"]) for fact in result["operands"]] == [
        ("prior", "394328000000"), ("current", "383285000000"),
    ]
    assert any("53 weeks" in caveat and "52 weeks" in caveat for caveat in result["scope_caveats"])
    assert any("weaker foreign currencies" in caveat for caveat in result["scope_caveats"])
    assert [item["id"] for item in result["citations"]] == [
        "prior", "current", "note-1", "note-2", "note-13", "foreign_currency_impact",
    ]
    for citation_id, phrase, character in (
        ("prior", "394,328", 499783), ("current", "383,285", 499115),
        ("note-1", "2023 spanned 53 weeks", 737420),
        ("note-2", "control of the products or services", 745622),
        ("note-13", "Net sales for geographic segments", 1306706),
        ("foreign_currency_impact", "accounted for more than the entire year-over-year decrease", 356642),
    ):
        citation = client.get(f"{base}/growth/citations/{citation_id}?prior=2022&current=2023")
        assert citation.status_code == 200
        assert phrase in citation.text
        assert f"HTML line 4, character {character}" in citation.text

    record: dict[str, Any] = {}
    assert ask_revenue(source, QUESTION, propose, record=record) == result
    saved = tmp_path / "growth.json"
    saved.write_text(json.dumps(record), encoding="utf-8")
    assert success("replay-ask", str(saved), "--store", str(store.root)) == result

    collection_record = tmp_path / "collection-growth.json"
    collection = success(
        "ask-collection", "What was Apple Inc.'s revenue growth from FY2022 to FY2023?",
        "--store", str(store.root), "--record", str(collection_record),
    )
    assert collection["percent"] == result["percent"]
    parent, = [item for item in collection["citations"] if "table_locators" in item]
    assert "CONSOLIDATED STATEMENTS OF OPERATIONS" in client.get(parent["href"]).text
    assert success("replay-collection", str(collection_record), "--store", str(store.root)) == collection


@pytest.mark.parametrize(("prior", "gap", "supported", "citation_ids"), [
    (2020, "FY2020 is absent from the consolidated revenue statement", [2023],
     ["current", "note-1", "note-2", "note-13", "statement-periods"]),
    (2021, "verified comparative and current pair", [2021, 2023], ["prior", "current", "note-1", "note-2", "note-13"]),
])
def test_apple_unsupported_growth_keeps_verified_observations_and_replays(
    tmp_path: Path, prior: int, gap: str, supported: list[int], citation_ids: list[str],
) -> None:
    store = SourceStore(tmp_path / "store")
    source = store.ingest_bytes(gzip.decompress(ARCHIVE.read_bytes()), provenance="local_original")
    question = f"What was revenue growth from FY{prior} to FY2023?"
    saved = tmp_path / "growth-gap.json"
    result = success("ask", source["source_id"], question, "--store", str(store.root), "--record", str(saved))
    assert result["status"] == "unavailable"
    assert result["percent"] is result["absolute_change"] is None
    assert result["trace"] == []
    assert result["comparison_basis"] is None and result["scope_caveats"] == []
    assert gap in result["issues"][0]["detail"]
    assert [fact["reporting_period"]["fiscal_year"] for fact in result["operands"]] == supported
    assert all(fact["status"] == "verified" for fact in result["operands"])
    assert [citation["id"] for citation in result["citations"]] == citation_ids
    record = json.loads(saved.read_text(encoding="utf-8"))
    assert record["model_request"] is record["proposed_plan"] is None
    assert success("replay-ask", str(saved), "--store", str(store.root)) == result
    client = create_app(store, tmp_path).test_client()
    base = f'/api/sources/{source["source_id"]}/growth/citations'
    query = f"?prior={prior}&current=2023"
    assert "383,285" in client.get(base + "/current" + query).text
    if prior == 2020:
        assert result["issues"][0]["code"] == "absent"
        assert client.get(base + "/prior" + query).status_code == 404
        headers = client.get(base + "/statement-periods" + query)
        assert headers.status_code == 200
        for text in ("CONSOLIDATED STATEMENTS OF OPERATIONS", "Total net sales", "September 25, 2021",
                     "September 24, 2022", "September 30, 2023", source["source_hash"]):
            assert text in " ".join(headers.text.split())


def test_apple_lookup_distinguishes_absent_and_unverified_years(tmp_path: Path) -> None:
    store = SourceStore(tmp_path / "store")
    source = store.ingest_bytes(gzip.decompress(ARCHIVE.read_bytes()), provenance="local_original")
    later = store.ingest_bytes(gzip.decompress(
        (ARCHIVE.parents[3] / "phase05/originals/aapl-20240928.htm.gz").read_bytes()
    ), provenance="local_original")
    for filing, year, code in ((source, 2020, "absent"), (later, 2024, "unverified")):
        saved = tmp_path / f"lookup-gap-{year}.json"
        question = f"What was revenue in FY{year}?"
        result = success("ask", filing["source_id"], question, "--store", str(store.root), "--record", str(saved))
        assert result["status"] == "evidence_unavailable"
        assert result["reason"] == code
        assert success("replay-ask", str(saved), "--store", str(store.root)) == result
        client = create_app(store, tmp_path, planner=lambda _: pytest.fail("Evidence gap reached the planner")).test_client()
        base = f'/api/sources/{filing["source_id"]}/lookup'
        assert client.post(base, json={"question": question}, headers={"X-Frag-Ask": "1"}).get_json() == result
        headers = client.get(f"{base}/citations/{year}/statement-periods")
        assert headers.status_code == (200 if code == "absent" else 404)
        if code == "unverified":
            assert "disclosures" in result["message"]
            assert result["citations"] == []


def test_incomplete_period_headers_cannot_establish_absence(tmp_path: Path) -> None:
    original = gzip.decompress(ARCHIVE.read_bytes())
    header = b"September 24,<br/>2022</span></td>"
    # A synthetic mutation leaves the FY2022 revenue cell under a blank header.
    # The consolidated statement has the first occurrence of this header.
    original = original.replace(header, b"</span></td>", 1)
    assert b"394,328</ix:nonFraction>" in original
    store = SourceStore(tmp_path / "store")
    source = store.ingest_bytes(original, provenance="local_original")
    result = success("ask", source["source_id"], "What was revenue in FY2022?", "--store", str(store.root))
    assert result["reason"] == "unverified"
    assert "did not establish the statement periods" in result["message"]
    assert result["citations"] == []


def test_pre_growth_apple_question_and_collection_records_still_replay(tmp_path: Path) -> None:
    store = SourceStore(tmp_path / "store")
    store.ingest_bytes(gzip.decompress(ARCHIVE.read_bytes()), provenance="local_original")
    # Recorded with the baseline immediately preceding #23 and a fixed planner.
    records = json.loads(gzip.decompress(LEGACY_REPLAYS.read_bytes()))
    for name, record in records.items():
        saved = tmp_path / f"{name}.json"
        saved.write_text(json.dumps(record), encoding="utf-8")
        command = "replay-collection" if name == "replay-collection-growth" else name
        expected = record["outcome"] if command == "replay-collection" else record["result"]
        assert success(command, str(saved), "--store", str(store.root)) == expected


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
     "note 1 boundary or content"),
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
    growth = client.post(base, json={"question": QUESTION}, headers={"X-Frag-Ask": "1"}).get_json()
    assert growth["status"] == "unavailable"
    assert growth["percent"] is None and growth["trace"] == []
    assert any(gap in issue["detail"] for issue in growth["issues"])
    assert growth["citations"] == []


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
