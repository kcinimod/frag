"""Filing-scoped lookup against preserved Phase 5 development evidence."""

import gzip
import json
import socket
from pathlib import Path
from typing import Any

import pytest
from test_source_workflow import success

from frag import cli
from frag.lookup import ask_revenue
from frag.store import SourceStore
from frag.web import create_app

ORIGINALS = Path(__file__).parents[1] / "artifacts/phase05/originals"
AMAZON = ORIGINALS / "amzn-20231231.htm.gz"


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
