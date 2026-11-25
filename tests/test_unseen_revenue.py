"""Filing-scoped lookup against preserved Phase 5 development evidence."""

import gzip
import json
import socket
from pathlib import Path
from typing import Any

import pytest
from test_chat_growth import growth_plan
from test_source_workflow import success

from frag import cli
from frag.lookup import ask_revenue
from frag.store import SourceStore
from frag.web import create_app

ORIGINALS = Path(__file__).parents[1] / "artifacts/phase05/originals"
AMAZON = ORIGINALS / "amzn-20231231.htm.gz"
INTEL = ORIGINALS / "intc-20231230.htm.gz"


def test_unseen_issuer_growth_uses_reported_periods_and_reopens_both_cells(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    store = SourceStore(tmp_path / "store")
    source = store.ingest_bytes(gzip.decompress(INTEL.read_bytes()), provenance="local_original")
    question = "What was revenue growth from FY2022 to FY2023?"

    def propose(payload: dict[str, Any]) -> str:
        prompt = json.loads(payload["messages"][1]["content"].splitlines()[0])
        by_year = {fact["reporting_period"]["fiscal_year"]: fact["fact_id"] for fact in prompt["evidence"]}
        return json.dumps(growth_plan(by_year[2022], by_year[2023]))

    monkeypatch.setattr(cli, "propose_lookup", propose)
    saved = tmp_path / "growth.json"
    assert cli.main(["ask", source["source_id"], question, "--store", str(store.root),
                     "--record", str(saved)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "calculated"
    assert result["percent"] == {"unit": "percent", "value": "-14.00"}
    assert result["trace"][0]["result"] == "-8826000000"
    assert [(fact["role"], fact["reporting_period"]["start"], fact["reporting_period"]["end"],
             fact["normalized_amount"]) for fact in result["operands"]] == [
        ("prior", "2021-12-26", "2022-12-31", "63054000000"),
        ("current", "2023-01-01", "2023-12-30", "54228000000"),
    ]
    assert any("FY2022 spans 53 weeks" in item and "FY2023 spans 52 weeks" in item for item in result["scope_caveats"])
    assert result["comparison_basis"]
    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}'
    assert client.post(base + "/lookup", json={"question": question}, headers={"X-Frag-Ask": "1"}).get_json() == result
    for citation, phrases in {
        "prior": ("Dec 31, 2022", "63,054", "In Millions", "iso4217:USD"),
        "current": ("Dec 30, 2023", "54,228", "In Millions", "iso4217:USD"),
        "note-1-consolidation": ("2022 was a 53-week fiscal year",),
        "note-2-revenue": ("transfer of control",),
    }.items():
        response = client.get(f"{base}/growth/citations/{citation}?prior=2022&current=2023")
        assert response.status_code == 200
        assert all(phrase in response.text for phrase in phrases)
    assert success("replay-ask", str(saved), "--store", str(store.root)) == result


def test_growth_requiring_equal_fiscal_years_keeps_both_cited_lookups(tmp_path: Path) -> None:
    store = SourceStore(tmp_path / "store")
    source = store.ingest_bytes(gzip.decompress(INTEL.read_bytes()), provenance="local_original")

    def propose(payload: dict[str, Any]) -> str:
        evidence, = json.loads(payload["messages"][1]["content"])["evidence"]
        return json.dumps({"operation": "lookup", "fact_id": evidence["fact_id"]})

    client = create_app(store, tmp_path, planner=propose).test_client()
    headers = {"X-Frag-Ask": "1"}
    base = f'/api/sources/{source["source_id"]}/lookup'
    for year, amount in [(2022, "63054000000"), (2023, "54228000000")]:
        lookup = client.post(base, json={"question": f"What was revenue in FY{year}?"}, headers=headers).get_json()
        assert lookup["status"] == "answered"
        assert lookup["fact"]["normalized_amount"] == amount
        assert client.get(f"{base}/citations/{year}/revenue").status_code == 200

    question = "What was reported consolidated revenue growth from FY2022 to FY2023 using equal-length fiscal years?"
    saved = tmp_path / "partial.json"
    result = success("ask", source["source_id"], question, "--store", str(store.root), "--record", str(saved))
    assert client.post(base, json={"question": question}, headers=headers).get_json() == result
    assert result["status"] == "unavailable"
    assert result["percent"] is result["absolute_change"] is None
    assert result["trace"] == []
    issue, = result["issues"]
    assert issue["code"] == "incompatible"
    assert all(text in issue["detail"] for text in ["FY2022 spans 53 weeks", "FY2023 spans 52 weeks"])
    assert all(fact["status"] == "verified" for fact in result["operands"])
    assert [fact["normalized_amount"] for fact in result["operands"]] == ["63054000000", "54228000000"]
    for role, amount in [("prior", "63,054"), ("current", "54,228")]:
        assert role in {item["id"] for item in result["citations"]}
        url = f'/api/sources/{source["source_id"]}/growth/citations/{role}?prior=2022&current=2023'
        assert amount in client.get(url).text
    assert success("replay-ask", str(saved), "--store", str(store.root)) == result


@pytest.mark.parametrize(("prior", "percent"), [(2022, "-14.00"), (2021, None)])
def test_collection_growth_respects_the_original_comparison_pair(
    tmp_path: Path, prior: int, percent: str | None,
) -> None:
    store = SourceStore(tmp_path / "store")
    store.ingest_bytes(gzip.decompress(INTEL.read_bytes()), provenance="local_original")
    saved = tmp_path / "collection.json"
    result = success(
        "ask-collection", f"What was Intel Corporation revenue growth from FY{prior} to FY2023?",
        "--store", str(store.root), "--record", str(saved),
    )
    client = create_app(store, tmp_path).test_client()
    if percent is None:
        assert result["status"] == "evidence_unavailable"
        assert result["percent"] is None
        assert result["stop_reason"] == "incompatible"
        assert {item["fact"]["reporting_period"]["fiscal_year"] for item in result["observations"]} == {prior, 2023}
        for item in result["observations"]:
            assert client.get(item["citation"]["href"]).status_code == 200
    else:
        assert result["status"] == "calculated"
        assert result["percent"]["value"] == percent
    assert result["citations"]
    for citation in result["citations"]:
        assert client.get(citation["href"]).status_code == 200
    assert success("replay-collection", str(saved), "--store", str(store.root)) == result


def test_lookup_with_a_separate_title_table_opens_statement_and_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def deny_network(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Offline lookup opened a socket")

    monkeypatch.setattr(socket, "socket", deny_network)
    path = tmp_path / "intc-20231230.htm"
    path.write_bytes(gzip.decompress(INTEL.read_bytes()))
    store = SourceStore(tmp_path / "store")
    source = success("ingest", str(path), "--provenance", "local_original", "--store", str(store.root))
    path.unlink()

    def propose(payload: dict[str, Any]) -> str:
        evidence, = json.loads(payload["messages"][1]["content"])["evidence"]
        assert evidence["reporting_period"]["fiscal_year"] == 2023
        return json.dumps({"operation": "lookup", "fact_id": evidence["fact_id"]})

    question = "What was revenue in FY2023?"
    monkeypatch.setattr(cli, "propose_lookup", propose)
    record = tmp_path / "answer.json"
    assert cli.main(["ask", source["source_id"], question, "--store", str(store.root),
                     "--record", str(record)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "answered"
    fact = result["fact"]
    assert (fact["raw_amount"], fact["normalized_amount"], fact["currency"], fact["scale"], fact["scope"]) == (
        "54,228", "54228000000", "USD", 1_000_000, "consolidated",
    )
    assert fact["inline_xbrl"]["fact_element_id"] == "f-44"
    assert (fact["reporting_period"]["start"], fact["reporting_period"]["end"]) == ("2023-01-01", "2023-12-30")
    prior = next(item for item in source["facts"] if item["reporting_period"]["fiscal_year"] == 2022)
    assert (prior["status"], prior["raw_amount"], prior["reporting_period"]["start"]) == (
        "verified", "63,054", "2021-12-26",
    )
    assert source["verification_reference"] is None
    assert success("replay-ask", str(record), "--store", str(store.root)) == result

    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}/lookup'
    assert client.post(base, json={"question": question}, headers={"X-Frag-Ask": "1"}).get_json() == result
    for citation, phrases in {
        "revenue": ("Consolidated Statements of Income", "Dec 30, 2023", "In Millions", "Net revenue", "54,228"),
        "note-1-consolidation": ("Basis of Presentation", "2022 was a 53-week fiscal year", "intercompany accounts"),
        "note-2-revenue": ("Revenue Recognition", "transfer of control", "cooperative advertising programs"),
    }.items():
        response = client.get(f"{base}/citations/2023/{citation}")
        assert response.status_code == 200
        assert all(phrase in response.text for phrase in phrases)

    collection_record = tmp_path / "collection.json"
    collection = success(
        "ask-collection", "What was Intel Corporation revenue in FY2023?",
        "--store", str(store.root), "--record", str(collection_record),
    )
    assert collection["status"] == "answered"
    assert collection["fact"]["fact_id"] == fact["fact_id"]
    assert success("replay-collection", str(collection_record), "--store", str(store.root)) == collection
    assert {citation["id"] for citation in collection["citations"]} == {
        "revenue", "note-1-consolidation", "note-2-revenue",
    }
    for citation in collection["citations"]:
        assert client.get(citation["href"]).status_code == 200


def test_conflicting_fiscal_calendar_keeps_the_affected_observation_provisional(tmp_path: Path) -> None:
    original = gzip.decompress(INTEL.read_bytes())
    disclosure = b"2022 was a 53-week fiscal year"
    assert original.count(disclosure) == 1
    store = SourceStore(tmp_path / "store")
    # Deliberately contradict the inline XBRL annual duration in a synthetic mutation.
    source = store.ingest_bytes(original.replace(disclosure, b"2022 was a 52-week fiscal year"),
                                provenance="local_original")

    def propose(_: dict[str, Any]) -> str:
        pytest.fail("Provisional revenue reached the planner")

    result = ask_revenue(source, "What was revenue in FY2022?", propose)
    assert result["status"] == "evidence_unavailable"
    assert "duration conflicts" in result["message"]
    statuses = {item["reporting_period"]["fiscal_year"]: item["status"] for item in source["facts"]}
    assert statuses == {2021: "verified", 2022: "provisional", 2023: "verified"}


@pytest.mark.parametrize(("before", "after", "verified_years"), [
    (b"include the accounts of Intel and our", b"include the accounts of Example Subsidiary and our", set()),
    (b"We have reclassified certain prior period amounts to conform to current period presentation.",
     b"Revenue for fiscal 2023 is misstated. The amount should not be relied on until corrected.", {2021, 2022}),
    (b"We have reclassified certain prior period amounts to conform to current period presentation.",
     b"For fiscal 2023, see the consolidated revenue line in the statement. "
     b"The amount should not be relied on until corrected.", {2021, 2022}),
    (b"We have reclassified certain prior period amounts to conform to current period presentation.",
     b"Prior-period segment revenues were recast to conform to the current segment presentation. "
     b"This did not change reported consolidated revenue.", {2021, 2022, 2023}),
])
def test_dated_statement_disclosures_qualify_the_affected_observations(
    tmp_path: Path, before: bytes, after: bytes, verified_years: set[int],
) -> None:
    original = gzip.decompress(INTEL.read_bytes())
    assert original.count(before) >= 1
    # These synthetic mutations exercise the checks after intake with a local-original claim.
    source = SourceStore(tmp_path / "store").ingest_bytes(
        original.replace(before, after, 1), provenance="local_original",
    )

    def propose(_: dict[str, Any]) -> str:
        pytest.fail("Provisional revenue reached the planner")

    assert {item["reporting_period"]["fiscal_year"] for item in source["facts"]
            if item["status"] == "verified"} == verified_years
    fact = next(item for item in source["facts"] if item["reporting_period"]["fiscal_year"] == 2023)
    assert fact["raw_amount"] == "54,228"
    if 2023 not in verified_years:
        result = ask_revenue(source, "What was revenue in FY2023?", propose)
        assert result["status"] == "evidence_unavailable"
        assert "applicable_notes" in result["message"]


def test_unseen_issuer_lookup_opens_original_evidence_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def deny_network(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Offline lookup opened a socket")

    monkeypatch.setattr(socket, "socket", deny_network)
    path = tmp_path / "amzn-20231231.htm"
    path.write_bytes(gzip.decompress(AMAZON.read_bytes()))
    store = SourceStore(tmp_path / "store")
    source = success("ingest", str(path), "--provenance", "local_original", "--store", str(store.root))
    path.unlink()

    def propose(payload: dict[str, Any]) -> str:
        evidence, = json.loads(payload["messages"][1]["content"])["evidence"]
        assert evidence["reporting_period"]["fiscal_year"] == 2023
        return json.dumps({"operation": "lookup", "fact_id": evidence["fact_id"]})

    client = create_app(store, tmp_path, planner=propose).test_client()
    base = f'/api/sources/{source["source_id"]}/lookup'
    question = "What was revenue in FY2023?"
    result = client.post(base, json={"question": question}, headers={"X-Frag-Ask": "1"}).get_json()
    assert result["status"] == "answered"
    fact = result["fact"]
    assert (fact["company"], fact["raw_amount"], fact["normalized_amount"]) == (
        "AMAZON.COM, INC.", "574,785", "574785000000",
    )
    assert (fact["currency"], fact["scale"], fact["scope"]) == ("USD", 1_000_000, "consolidated")
    assert (fact["reporting_period"]["start"], fact["reporting_period"]["end"]) == (
        "2023-01-01", "2023-12-31",
    )
    assert source["verification_reference"] is None

    excerpts = {}
    for citation in result["citations"]:
        response = client.get(f'{base}/citations/2023/{citation["id"]}')
        assert response.status_code == 200
        excerpts[citation["id"]] = response.text
    for phrase in ("Total net sales", "Year Ended December 31", "2023", "in millions", "574,785", "iso4217:USD"):
        assert phrase in excerpts["revenue"]
    assert ("Intercompany balances and transactions between consolidated entities are eliminated"
            in excerpts["note-1-consolidation"])
    assert "including sales and indirect taxes" in excerpts["note-1-revenue"]

    monkeypatch.setattr(cli, "propose_lookup", propose)
    saved = tmp_path / "answer.json"
    assert cli.main(["ask", source["source_id"], question, "--store", str(store.root),
                     "--record", str(saved)]) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert success("replay-ask", str(saved), "--store", str(store.root)) == result

    prior = next(item for item in source["facts"] if item["reporting_period"]["fiscal_year"] == 2022)
    wrong_plan = json.dumps({"operation": "lookup", "fact_id": prior["fact_id"]})
    rejected = ask_revenue(source, question, lambda _: wrong_plan)
    assert rejected["status"] == "invalid_plan"
    assert "fact" not in rejected


@pytest.mark.parametrize(("original_text", "changed_text", "reason"), [
    (b"id=\"f-137\">574,785</ix:nonFraction>", b"id=\"f-137\">574,785</ix:nonFraction>9",
     "displayed revenue amount"),
    (b'scale="6" id="f-137"', b'scale="3" id="f-137"', "visible statement scale"),
    (b'<xbrli:unit id="usd"><xbrli:measure>iso4217:USD',
     b'<xbrli:unit id="usd"><xbrli:measure>iso4217:CAD', "visible statement currency"),
    (b'contextRef="c-1" decimals="-6" name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"'
     b' format="ixt:num-dot-decimal" scale="6" id="f-137"',
     b'contextRef="c-8" decimals="-6" name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"'
     b' format="ixt:num-dot-decimal" scale="6" id="f-137"',
     "displayed fiscal year-end"),
    (b"including sales and indirect taxes", b"including unrelated charges", "applicable_notes"),
    (b"transactions between consolidated entities are eliminated",
     b"transactions between consolidated entities are not eliminated", "applicable_notes"),
    (b"(in millions, except per share data)",
     b"(in millions of Canadian dollars, except per share data)", "currency or scale declaration"),
    (b"FINANCIAL INSTRUMENTS</ix:nonNumeric></span></div>",
     b"FINANCIAL INSTRUMENTS</ix:nonNumeric></span></div>"
     b"<div>FY2023 net sales were on a different basis and should not be used until corrected.</div>",
     "applicable_notes"),
])
def test_synthetic_evidence_conflicts_block_lookup(
    tmp_path: Path, original_text: bytes, changed_text: bytes, reason: str,
) -> None:
    original = gzip.decompress(AMAZON.read_bytes())
    assert original_text in original
    # Exercise the evidence checks after intake with a local-original claim.
    source = SourceStore(tmp_path).ingest_bytes(
        original.replace(original_text, changed_text, 1), provenance="local_original",
    )

    def propose(_: dict[str, Any]) -> str:
        pytest.fail("Unverified evidence reached the planner")

    result = ask_revenue(source, "What was revenue in FY2023?", propose)
    assert result["status"] == "evidence_unavailable"
    assert reason in result["message"]
    if reason in {"applicable_notes", "visible statement scale"}:
        fact = next(item for item in source["facts"] if item["reporting_period"]["fiscal_year"] == 2023)
        assert fact["status"] == "provisional"
        assert fact["normalized_amount"] == "574785000000"
        assert fact["locators"]["value"]["table"] == 38


def test_statement_citation_skips_hidden_text_and_handles_multiline_cells(tmp_path: Path) -> None:
    original = gzip.decompress(AMAZON.read_bytes())
    cell = b'id="f-137">574,785</ix:nonFraction>'
    assert original.count(cell) == 1
    original = original.replace(cell, cell + b'\n<span hidden>9</span>', 1)
    store = SourceStore(tmp_path)
    source = store.ingest_bytes(original, provenance="local_original")
    client = create_app(store, tmp_path).test_client()
    result = client.get(f'/api/sources/{source["source_id"]}/lookup/citations/2023/revenue')
    assert result.status_code == 200
    assert result.text.splitlines()[-1] == "574,785"
