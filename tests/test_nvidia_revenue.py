"""Exercise Nvidia's opened Phase 6 cases using the independent custody review."""

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
REVIEWS = json.loads((ROOT / "tests/fixtures/phase06_nvidia_review.json").read_bytes())


def original_bytes(filename: str) -> bytes:
    return gzip.decompress((ROOT / "artifacts/phase06/originals" / (filename + ".gz")).read_bytes())


@pytest.mark.parametrize("filename", REVIEWS)
def test_nvidia_preserves_reviewed_statement_observations(filename: str, tmp_path: Path) -> None:
    original = original_bytes(filename)
    review = REVIEWS[filename]
    source = SourceStore(tmp_path).ingest_bytes(original, provenance="local_original")
    assert source["source_hash"] == review["source"]["sha256"]
    evidence = review["evidence"]
    facts = {str(fact["reporting_period"]["fiscal_year"]): fact for fact in source["facts"]}
    assert facts.keys() == evidence["facts"].keys()
    lines = original.split(b"\n")
    for year, fact in facts.items():
        expected = evidence["facts"][year]
        verified = expected["verification"] == "inline_corroborated"
        assert fact["status"] == ("verified" if verified else "provisional"), fact["unresolved_requirements"]
        assert fact["metric_label"] == evidence["statement_row"]
        for field in ("raw_amount", "normalized_amount", "currency", "scale", "scope"):
            assert fact[field] == expected[field]
        assert fact["reporting_period"] == {
            "kind": "annual", "fiscal_year": int(year), "start": expected["period_start"], "end": expected["period_end"],
        }
        spans = {
            "table": evidence["locators"]["statement"],
            "metric_label": evidence["locators"]["revenue_row"],
            "annual_header": evidence["locators"]["period_header"],
            "unit_header": evidence["locators"]["statement_title_and_units"],
            "year_header": expected["locators"]["period_cell"],
            "value": expected["locators"]["statement_cell"],
        }
        if verified:
            assert {key: fact["inline_xbrl"][key] for key in ("concept", "context_id", "fact_element_id")} == {
                "concept": expected["concept"], "context_id": expected["context_id"],
                "fact_element_id": expected["element_id"],
            }
            spans.update(inline_fact=expected["locators"]["inline_fact"],
                         inline_context=expected["locators"]["context"], currency_measure=expected["locators"]["unit"])
            for note in evidence["applicable_notes"]:
                span = note["locator"]
                start, end = span["start_byte"], span["end_byte"]
                assert sha256(original[start:end]).hexdigest() == span["sha256"]
                assert any(
                    byte_position(lines, item["locator"]["start"]) <= start
                    and end <= byte_position(lines, item["locator"]["end_exclusive"])
                    for item in fact["applicable_notes"]
                ), note["label"]
        else:
            assert fact["inline_xbrl"] is None
            assert "inline_xbrl_verification" in fact["unresolved_requirements"]
        for key, span in spans.items():
            start, end = span["start_byte"], span["end_byte"]
            assert sha256(original[start:end]).hexdigest() == span["sha256"]
            assert start <= byte_position(lines, fact["locators"][key]) < end, key
        title = byte_position(lines, fact["locators"]["statement_heading"])
        assert b"consolidated statements of income" in original[title:title + 500].lower()


def test_nvidia_requires_inline_start_to_match_disclosed_fiscal_calendar(tmp_path: Path) -> None:
    filename = "nvda-20250126.htm"
    original = original_bytes(filename)
    span = REVIEWS[filename]["evidence"]["facts"]["2023"]["locators"]["context"]
    start, end = span["start_byte"], span["end_byte"]
    context = original[start:end]
    # Synthetic control moves only the inline start back one week.
    assert b">2022-01-31<" in context
    changed = original[:start] + context.replace(b">2022-01-31<", b">2022-01-24<") + original[end:]
    source = SourceStore(tmp_path).ingest_bytes(changed, provenance="local_original")
    facts = {fact["reporting_period"]["fiscal_year"]: fact for fact in source["facts"]}
    assert {year: fact["status"] for year, fact in facts.items()} == {
        2023: "provisional", 2024: "verified", 2025: "verified",
    }
    assert facts[2023]["reporting_period"]["start"] == "2022-01-31"
    assert "inline_xbrl_verification" in facts[2023]["unresolved_requirements"]


def test_nvidia_localizes_a_disclosed_week_count_conflict(tmp_path: Path) -> None:
    original = original_bytes("nvda-20250126.htm")
    disclosed = b"Fiscal years 2025, 2024 and 2023 were all 52-week years."
    assert original.count(disclosed) == 1
    # Synthetic control contradicts only FY2023's week count.
    changed = original.replace(
        disclosed, b"Fiscal years 2025 and 2024 were both 52-week years and fiscal year 2023 was a 53-week year.",
    )
    source = SourceStore(tmp_path).ingest_bytes(changed, provenance="local_original")
    facts = {fact["reporting_period"]["fiscal_year"]: fact for fact in source["facts"]}
    assert {year: fact["status"] for year, fact in facts.items()} == {
        2023: "provisional", 2024: "verified", 2025: "verified",
    }
    assert "fiscal_calendar_verification" in facts[2023]["unresolved_requirements"]
    assert source["comparison"]["status"] == "compatible"


def test_nvidia_verifies_observations_despite_a_comparison_disclosure(tmp_path: Path) -> None:
    original = original_bytes("nvda-20250126.htm")
    disclosure = b"Certain prior fiscal year balances have been reclassified to conform to the current fiscal year presentation."
    assert original.count(disclosure) == 1
    # Synthetic control replaces the general reclassification disclosure with a comparison qualification.
    changed = original.replace(
        disclosure, b"Reported consolidated revenue for fiscal years 2024 and 2025 is not directly comparable.",
    )
    source = SourceStore(tmp_path).ingest_bytes(changed, provenance="local_original")
    assert {fact["reporting_period"]["fiscal_year"]: fact["status"] for fact in source["facts"]} == {
        2023: "verified", 2024: "verified", 2025: "verified",
    }
    assert source["comparison"]["status"] == "unresolved"
    assert source["comparison"]["evidence"]


@pytest.mark.parametrize(
    ("filename", "case"), [(filename, case) for filename, review in REVIEWS.items() for case in review["cases"]],
    ids=[case["case_id"] for review in REVIEWS.values() for case in review["cases"]],
)
def test_nvidia_public_filing_workflow_offline(
    filename: str, case: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def deny_network(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Offline filing workflow opened a socket")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, deny_network)
    metadata = REVIEWS[filename]["source"]
    path = tmp_path / filename
    path.write_bytes(original_bytes(filename))
    store = SourceStore(tmp_path / "store")
    source = success(
        "ingest", str(path), "--provenance", "local_original", "--store", str(store.root),
        "--company", metadata["issuer"], "--accession", metadata["accession"], "--form", metadata["form"],
        "--filing-date", metadata["filing_date"], "--source-url", metadata["source_url"],
    )
    path.unlink()
    facts = {fact["reporting_period"]["fiscal_year"]: fact["fact_id"] for fact in source["facts"]}
    years = case["years"]

    def propose(_: dict[str, Any]) -> str:
        if case["outcome"] == "present_unverifiable":
            pytest.fail("Provisional evidence reached the planner")
        if case["kind"] == "lookup":
            return json.dumps({"operation": "lookup", "fact_id": facts[years[0]]})
        return json.dumps(growth_plan(facts[years[0]], facts[years[1]]))

    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}'
    response = client.post(base + "/lookup", json={"question": case["question"]}, headers={"X-Frag-Ask": "1"})
    assert response.status_code == 200
    result = response.get_json()
    reviewed = REVIEWS[filename]["evidence"]["facts"]
    if case["outcome"] == "present_unverifiable":
        assert result["status"] == "evidence_unavailable" and result["reason"] == "unverified"
        assert result["fiscal_year"] == 2018
        assert "inline XBRL fact, context, and unit" in result["message"]
        assert "statement displays" in result["message"]
        assert "fact" not in result and "9,714" not in result["message"] and "9714000000" not in result["message"]
    else:
        if case["kind"] == "lookup":
            assert result["status"] == "answered", result
            assert result["fact"]["normalized_amount"] == reviewed["2025"]["normalized_amount"]
            routes = "/lookup/citations/2025/{key}"
            operands = {"revenue": 2025}
        else:
            assert result["status"] == "calculated", result
            assert result["percent"] == {"unit": "percent", "value": case["percent"]}
            assert [(step["operation"], step["result"]) for step in result["trace"]] == [
                ("subtract", case["absolute_change"]), ("divide", "69575/60922"), ("to_percent", case["percent"]),
            ]
            routes = "/growth/citations/{key}?prior=2024&current=2025"
            operands = {"prior": 2024, "current": 2025}
        excerpts = {}
        for citation in result["citations"]:
            key = citation["id"]
            excerpt = client.get(base + routes.format(key=key))
            assert excerpt.status_code == 200
            assert source["source_hash"] in excerpt.text
            excerpts[key] = excerpt.text.partition("\n\n")[2]
        for role, year in operands.items():
            for text in (reviewed[str(year)]["raw_amount"], str(year), "iso4217:USD", "millions", "Revenue"):
                assert text in excerpts[role]
        assert "reclassified to conform" in excerpts["note-1-comparative-presentation"]
        assert "were all 52-week years" in excerpts["note-1-fiscal-year"]
        assert "intercompany balances and transactions have been eliminated" in excerpts["note-1-consolidation"]
        assert "as, we satisfy a performance obligation" in excerpts["note-1-revenue"]

    monkeypatch.setattr(cli, "propose_lookup", propose)
    record = tmp_path / "ask.json"
    assert cli.main(["ask", source["source_id"], case["question"], "--store", str(store.root),
                     "--record", str(record)]) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert success("replay-ask", str(record), "--store", str(store.root)) == result
