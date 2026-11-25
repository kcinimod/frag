"""Cisco's opened 10-K through the public filing workflow."""

import gzip
import json
import re
import socket
from pathlib import Path
from typing import Any

import pytest
from test_chat_growth import growth_plan
from test_source_workflow import success

from frag import cli
from frag.store import SourceStore
from frag.web import create_app

ARCHIVE = Path(__file__).resolve().parents[1] / "artifacts/phase06/originals/csco-20240727.htm.gz"
LOOKUP = "What was reported consolidated revenue in FY2024?"
GROWTH = "How did reported consolidated revenue change from FY2023 to FY2024?"


def test_cisco_ingest_matches_reviewed_original_cells(tmp_path: Path) -> None:
    original = gzip.decompress(ARCHIVE.read_bytes())
    store = SourceStore(tmp_path)
    source = store.ingest_bytes(original, provenance="local_original")
    assert source["source_hash"] == "3df6a0e21e93cb933b6f5fa5684dece87d9ecbd115a59dd3960bf06db6bcb91b"
    expected = {
        2022: ("51,557", "51557000000", "2021-08-01", "2022-07-30", "f-131", 1383576),
        2023: ("56,998", "56998000000", "2022-07-31", "2023-07-29", "f-130", 1382908),
        2024: ("53,803", "53803000000", "2023-07-30", "2024-07-27", "f-129", 1382117),
    }
    assert {fact["reporting_period"]["fiscal_year"] for fact in source["facts"]} == expected.keys()
    lines = original.decode().split("\n")
    for fact in source["facts"]:
        period = fact["reporting_period"]
        assert (fact["status"], fact["currency"], fact["scale"], fact["scope"]) == (
            "verified", "USD", 1_000_000, "consolidated",
        )
        value = fact["locators"]["value"]
        byte_offset = len(("\n".join(lines[:value["line"] - 1]) + "\n"
                           + lines[value["line"] - 1][:value["character"] - 1]).encode())
        assert value["table"] == 56
        assert (fact["raw_amount"], fact["normalized_amount"], period["start"], period["end"],
                fact["inline_xbrl"]["fact_element_id"], byte_offset) == expected[period["fiscal_year"]]
    again = store.ingest_bytes(original, provenance="local_original")
    assert [fact["fact_id"] for fact in again["facts"]] == [fact["fact_id"] for fact in source["facts"]]
    assert store.inspect()["source_count"] == 1


def test_cisco_browser_answers_and_cli_replay_open_original_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def deny_network(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Offline Cisco workflow opened a socket")

    monkeypatch.setattr(socket, "socket", deny_network)
    path = tmp_path / "csco-20240727.htm"
    path.write_bytes(gzip.decompress(ARCHIVE.read_bytes()))
    store = SourceStore(tmp_path / "store")
    source = success("ingest", str(path), "--provenance", "local_original", "--store", str(store.root))
    path.unlink()
    fact_ids = {fact["reporting_period"]["fiscal_year"]: fact["fact_id"] for fact in source["facts"]}

    def propose(payload: dict[str, Any]) -> str:
        if "Use these exact inputs in the growth plan" in payload["messages"][1]["content"]:
            return json.dumps(growth_plan(fact_ids[2023], fact_ids[2024]))
        return json.dumps({"operation": "lookup", "fact_id": fact_ids[2024]})

    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}'
    monkeypatch.setattr(cli, "propose_lookup", propose)
    for question, status in ((LOOKUP, "answered"), (GROWTH, "calculated")):
        response = client.post(base + "/lookup", json={"question": question}, headers={"X-Frag-Ask": "1"})
        assert response.status_code == 200
        result = response.get_json()
        assert result["status"] == status
        if status == "answered":
            assert result["fact"]["normalized_amount"] == "53803000000"
        else:
            assert result["percent"] == {"unit": "percent", "value": "-5.61"}
            assert [step["operation"] for step in result["trace"]] == ["subtract", "divide", "to_percent"]
            assert result["trace"][0]["result"] == "-3195000000"
            assert "FY2024 includes Splunk revenue from the acquisition date." in result["scope_caveats"]

        excerpts = {}
        for citation in result["citations"]:
            citation_id = citation["id"]
            href = (f"/lookup/citations/2024/{citation_id}" if status == "answered"
                    else f"/growth/citations/{citation_id}?prior=2023&current=2024")
            excerpt = client.get(base + href)
            assert excerpt.status_code == 200
            excerpts[citation_id] = excerpt.text
        for snippet in ("Consolidated Statements of Operations", "July 27, 2024", "in millions", "iso4217:USD", "53,803"):
            assert snippet in excerpts["revenue" if status == "answered" else "current"]
        if status == "calculated":
            assert "56,998" in excerpts["prior"]
        assert "each 52-week fiscal years" in excerpts["note-1-consolidation"]
        assert "transfer of control" in excerpts["note-2-revenue"]
        assert "Splunk since the date of acquisition" in excerpts["note-4-acquisition-revenue"]
        assert "unaudited pro forma financial information" in excerpts["note-4-pro-forma-revenue"]

        saved = tmp_path / f"{status}.json"
        assert cli.main(["ask", source["source_id"], question, "--store", str(store.root),
                         "--record", str(saved)]) == 0
        assert json.loads(capsys.readouterr().out) == result
        assert success("replay-ask", str(saved), "--store", str(store.root)) == result


def _header_row(original: bytes) -> tuple[int, bytes]:
    start = 1374721  # Start of the independently reviewed statement.
    assert original[start:].startswith(b"<table")
    end = original.index(b"</table>", start)
    row = next(match for match in re.finditer(rb"<tr[>\s].*?</tr>", original[start:end])
               if b"July 27, 2024" in match[0])
    return start + row.start(), row[0]


def _replace_header(original: bytes, replacement: bytes) -> bytes:
    start, header = _header_row(original)
    return original[:start] + replacement + original[start + len(header):]


def test_cisco_layout_combines_dates_across_rows(tmp_path: Path) -> None:
    original = gzip.decompress(ARCHIVE.read_bytes())
    _, header = _header_row(original)
    # Synthetic layout variant retaining the original amounts and corroborating contexts.
    dates = rb"(July \d{2}), (20\d{2})"
    month_days = re.sub(dates, rb"\1,", header)
    years = re.sub(dates, rb"\2", header).replace(b"Years Ended", b"")
    store = SourceStore(tmp_path)
    changed = _replace_header(original, month_days + b"\n" + years)
    source = store.ingest_bytes(changed, provenance="local_original")
    assert [(fact["status"], fact["raw_amount"], fact["reporting_period"]["end"]) for fact in source["facts"]] == [
        ("verified", "51,557", "2022-07-30"),
        ("verified", "56,998", "2023-07-29"),
        ("verified", "53,803", "2024-07-27"),
    ]
    client = create_app(store, tmp_path).test_client()
    endpoint = f'/api/sources/{source["source_id"]}/lookup/citations'
    excerpt = client.get(endpoint + "/2024/revenue")
    assert excerpt.status_code == 200
    assert "July 27,\n2024" in excerpt.text
    inventory = client.get(endpoint + "/2021/statement-periods")
    assert inventory.status_code == 200
    assert "July 30," in inventory.text and "2022" in inventory.text


@pytest.mark.parametrize("conflict, reason", [
    ("statements", "one visible consolidated income statement"),
    ("header", "fiscal year columns are ambiguous"),
    ("contradictory_periods", "unambiguous period inventory"),
    ("inline", "displayed revenue amount"),
    ("acquisition_note", "applicable acquisition disclosures"),
])
def test_cisco_layout_stops_on_conflicting_evidence(tmp_path: Path, conflict: str, reason: str) -> None:
    original = gzip.decompress(ARCHIVE.read_bytes())
    if conflict == "statements":
        statement = original[1372991:1436266]
        assert b"Consolidated Statements of Operations" in statement and statement.endswith(b"</table>")
        changed = original.replace(statement, statement + statement.replace(b"53,803", b"53,804", 1), 1)
    elif conflict == "header":
        _, header = _header_row(original)
        changed = _replace_header(original, header.replace(b"July 29, 2023", b"July 29, 2024"))
    elif conflict == "contradictory_periods":
        _, header = _header_row(original)
        alternate = (header.replace(b"Years Ended", b"").replace(b"July 27, 2024", b"FY2023")
                     .replace(b"July 29, 2023", b"FY2022").replace(b"July 30, 2022", b"FY2021"))
        changed = _replace_header(original, header + alternate)
    elif conflict == "acquisition_note":
        assert b"since the date of acquisition" in original[1804359:1805203]
        changed = original[:1804359] + original[1805203:]
    else:
        tagged = b'id="f-129">53,803</ix:nonFraction>'
        assert original.count(tagged) == 1
        changed = original.replace(tagged, tagged + b"9", 1)

    # Synthetic mutations exercise evidence checks after intake with a local-original claim.
    store = SourceStore(tmp_path)
    source = store.ingest_bytes(changed, provenance="local_original")

    def unexpected_plan(_: dict[str, Any]) -> str:
        pytest.fail("Conflicting evidence reached the planner")

    client = create_app(store, tmp_path, planner=unexpected_plan).test_client()
    response = client.post(f'/api/sources/{source["source_id"]}/lookup', json={"question": LOOKUP},
                           headers={"X-Frag-Ask": "1"})
    result = response.get_json()
    assert result["status"] == "evidence_unavailable"
    assert reason in result["message"]
    if conflict in {"inline", "acquisition_note"}:
        growth = client.post(f'/api/sources/{source["source_id"]}/lookup', json={"question": GROWTH},
                             headers={"X-Frag-Ask": "1"}).get_json()
        assert growth["status"] == "unavailable"
        assert [item["reporting_period"]["fiscal_year"] for item in growth["operands"]] == [2023]
