"""Exercise the opened Ford, McDonald's, and Disney filings against custody review."""

import gzip
import json
import socket
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from test_shared_year_revenue import byte_position
from test_source_workflow import success

from frag.store import SourceStore

ROOT = Path(__file__).resolve().parents[1]
REVIEWS = json.loads((ROOT / "tests/fixtures/phase06_ford_mcdonalds_disney_review.json").read_bytes())
CASES = {case["case_id"]: case for review in REVIEWS.values() for case in review["cases"]}


def original_bytes(filename: str) -> bytes:
    return gzip.decompress((ROOT / "artifacts/phase06/originals" / (filename + ".gz")).read_bytes())


@pytest.mark.parametrize("filename", REVIEWS)
def test_verifies_reviewed_revenue(filename: str, tmp_path: Path) -> None:
    review = REVIEWS[filename]
    original = original_bytes(filename)
    assert sha256(original).hexdigest() == review["source"]["sha256"]
    source = SourceStore(tmp_path).ingest_bytes(original, provenance="local_original")
    evidence = review["evidence"]
    facts = {str(fact["reporting_period"]["fiscal_year"]): fact for fact in source["facts"]}
    assert facts.keys() == evidence["facts"].keys(), source["diagnostics"]
    lines = original.split(b"\n")
    for year, fact in facts.items():
        expected = evidence["facts"][year]
        assert fact["status"] == "verified", (fact["unresolved_requirements"], source["diagnostics"])
        assert fact["metric_label"] == evidence["statement_row"]
        for field in ("raw_amount", "normalized_amount", "currency", "scale", "scope"):
            assert fact[field] == expected[field]
        assert fact["reporting_period"] == {
            "kind": "annual", "fiscal_year": int(year),
            "start": expected["period_start"], "end": expected["period_end"],
        }
        for key, expected_key in (
            ("fact_element_id", "element_id"), ("context_id", "context_id"), ("concept", "concept"),
        ):
            assert fact["inline_xbrl"][key] == expected[expected_key]
        for locator, span in {
            "table": evidence["locators"]["statement"],
            "metric_label": evidence["locators"]["revenue_row"],
            "year_header": expected["locators"]["period_cell"],
            "value": expected["locators"]["statement_cell"],
            "inline_fact": expected["locators"]["inline_fact"],
            "inline_context": expected["locators"]["context"],
            "currency_measure": expected["locators"]["unit"],
        }.items():
            start, end = span["start_byte"], span["end_byte"]
            assert sha256(original[start:end]).hexdigest() == span["sha256"]
            assert start <= byte_position(lines, fact["locators"][locator]) < end
        for note in evidence["applicable_notes"]:
            span = note["locator"]
            start, end = span["start_byte"], span["end_byte"]
            assert sha256(original[start:end]).hexdigest() == span["sha256"]
            assert any(
                byte_position(lines, item["locator"]["start"]) <= start < end
                <= byte_position(lines, item["locator"]["end_exclusive"])
                for item in fact["applicable_notes"]
            ), note["label"]


@pytest.mark.parametrize(("filename", "before", "after", "reason"), [
    ("f-20241231.htm", b"disaggregate our revenue by major source",
     b"disaggregate selected amounts", "applicable filing disclosures"),
    ("mcd-20241231.htm", b">2023</span>",
     b">2024</span>", "fiscal year columns are ambiguous"),
    ("dis-20240928.htm", b"were fifty-two week years",
     b"were fifty-two week years. Fiscal 2024 was a fifty-three week year",
     "applicable fiscal-calendar disclosure"),
    ("dis-20240928.htm", b"were fifty-two week years",
     b"were fifty-two week years. The fiscal year ends on the Sunday closest to September 30",
     "applicable fiscal-calendar disclosure"),
])
def test_asks_explain_unresolved_evidence(
    filename: str, before: bytes, after: bytes, reason: str, tmp_path: Path,
) -> None:
    # Synthetic controls change one piece of otherwise preserved evidence.
    original = original_bytes(filename)
    evidence = REVIEWS[filename]["evidence"]
    if filename.startswith("mcd-"):
        span = evidence["locators"]["period_header"]
        start, end = span["start_byte"], span["end_byte"]
        assert original[start:end].count(before) == 1
        changed = original[:start] + original[start:end].replace(before, after) + original[end:]
    else:
        assert original.count(before) == 1
        changed = original.replace(before, after)
    store = SourceStore(tmp_path)
    source = store.ingest_bytes(changed, provenance="synthetic")
    result = success("ask", source["source_id"], "What was reported consolidated revenue in FY2024?",
                     "--store", str(store.root))
    assert result["status"] == "evidence_unavailable", result
    assert "FY2024 revenue evidence gap." in result["message"]
    assert reason in result["message"]


def test_conflicting_disney_header_reports_evidence_gap(tmp_path: Path) -> None:
    filename = "dis-20240928.htm"
    original = original_bytes(filename)
    end = REVIEWS[filename]["evidence"]["locators"]["period_header"]["end_byte"]
    # Synthetic row places a second year directly above the FY2024 value.
    conflicting_row = (
        b'<tr><td colspan="3"/><td colspan="3">2023</td><td colspan="3"/>'
        b'<td colspan="3">Recast</td><td colspan="3"/><td colspan="3">2022</td></tr>'
    )
    changed = original[:end] + conflicting_row + original[end:]
    store = SourceStore(tmp_path)
    source = store.ingest_bytes(changed, provenance="synthetic")
    result = success("ask", source["source_id"], "What was reported consolidated revenue in FY2024?",
                     "--store", str(store.root))
    assert result["status"] == "evidence_unavailable", result
    assert "More than one row displays fiscal years" in result["message"]


def test_reviewed_answers_and_citations_reopen_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reuse the acceptance runner's public CLI and browser citation checks.
    monkeypatch.syspath_prepend(str(ROOT / "artifacts/phase04"))
    from sec_holdout_runner import ingest, replay_case  # type: ignore[import-not-found]

    def deny_network(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Offline filing workflow opened a socket")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, deny_network)
    phase = ROOT / "artifacts/phase06"
    run = json.loads(gzip.decompress((phase / "ford-mcdonalds-disney-validation.json.gz").read_bytes()))
    assert run["cases"].keys() == CASES.keys()
    sources = {}
    for filename, review in REVIEWS.items():
        original = tmp_path / filename
        original.write_bytes(original_bytes(filename))
        sources[filename] = ingest(tmp_path / "store", original, review["source"])
        original.unlink()
    for case_id, row in run["cases"].items():
        case = CASES[case_id]
        assert case["question"] == row["question"]
        assert replay_case(tmp_path / "store", case, sources[row["filename"]], row["live"]) == {"status": "matched"}
        result = row["live"]["result"]
        reviewed_facts = REVIEWS[row["filename"]]["evidence"]["facts"]
        if case["kind"] == "lookup":
            assert result["status"] == "answered"
            assert result["fact"]["normalized_amount"] == reviewed_facts["2024"]["normalized_amount"]
        else:
            assert result["status"] == "calculated"
            assert result["percent"] == {"unit": "percent", "value": case["percent"]}
            assert [(operand["status"], operand["normalized_amount"]) for operand in result["operands"]] == [
                ("verified", reviewed_facts[str(year)]["normalized_amount"]) for year in case["years"]
            ]
            assert [step["operation"] for step in result["trace"]] == ["subtract", "divide", "to_percent"]
            assert result["trace"][0]["result"] == case["absolute_change"]
            assert result["trace"][-1]["result"] == case["percent"]
        assert row["live"]["citations"]
        assert all(opened["http_status"] == 200 for opened in row["live"]["citations"].values())
