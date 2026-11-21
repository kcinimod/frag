import gzip
import json
from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

from frag.cli import main

ROOT = Path(__file__).resolve().parents[1]
ANCHOR = ROOT / "artifacts/phase01/originals/msft-20230630.htm.gz"
PRIOR = ROOT / "artifacts/phase03/originals/msft-10k_20220630.htm.gz"


def test_collection_cli_returns_verified_reporting_periods(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch,
) -> None:
    store_args = ["--store", str(tmp_path / "store")]

    def invoke(*args: str) -> dict[str, object]:
        assert main([*args, *store_args]) == 0
        output: dict[str, object] = json.loads(capsys.readouterr().out)
        return output

    anchor = tmp_path / "msft-20230630.htm"
    anchor.write_bytes(gzip.decompress(ANCHOR.read_bytes()))
    anchor_args = ("ingest", str(anchor), "--provenance", "local_original", "--filing-date", "2023-07-27")
    anchor_source = invoke(*anchor_args)
    prior = tmp_path / "msft-20220630.htm"
    prior.write_bytes(gzip.decompress(PRIOR.read_bytes()))
    prior_source = invoke("ingest", str(prior), "--provenance", "local_original",
                          "--accession", "0001564590-22-026876", "--filing-date", "2022-07-28")
    synthetic_source = invoke("ingest", str(ROOT / "tests/fixtures/synthetic_income.html"),
                              "--company", "Synthetic Example", "--provenance", "synthetic")
    before = invoke("index-collection")
    invoke(*anchor_args)
    assert before == invoke("index-collection")

    for ambiguous in ("FY2023 revenue", "Microsoft revenue", "Microsoft FY2022 or FY2023 revenue",
                      "Microsoft and Synthetic Example FY2022 revenue", "Microsoft FY2022 segment revenue",
                      "Microsoft FY2023 revenue guidance"):
        assert invoke("ask-collection", ambiguous)["status"] == "clarify"
    assert invoke("ask-collection", "Microsoft FY2021 revenue")["status"] == "evidence_unavailable"
    assert invoke("ask-collection", "Synthetic Example FY2023 revenue")["status"] == "evidence_unavailable"
    for phrasing in ("What was FY2023 revenue for Microsoft?", "Microsoft Corporation (MSFT) FY2023 revenue"):
        assert invoke("ask-collection", phrasing)["status"] == "answered"

    record = tmp_path / "lookup.json"
    answer = invoke("ask-collection", "What was Microsoft's revenue in FY2022?", "--record", str(record))
    run = json.loads(record.read_bytes())
    assert run["outcome"] == answer
    assert run["snapshot"] == before
    assert run["selected_evidence_ids"] == [run["outcome"]["fact"]["fact_id"]]
    assert run["outcome"]["fact"]["normalized_amount"] == "198270000000"
    assert run["outcome"]["fact"]["filing_date"] == "2023-07-27"
    assert run["outcome"]["citations"][0]["locator"]["line"] == 4403
    assert run["outcome"]["citations"][0]["source_id"] == anchor_source["source_id"]
    candidates = {(item["source_id"], item["reporting_period"]["fiscal_year"]): item["exclusions"]
                  for item in run["ranked_candidates"]}
    assert "unverified" in candidates[(prior_source["source_id"], 2022)]
    assert "different_reporting_period" in candidates[(anchor_source["source_id"], 2023)]
    assert "different_company" in candidates[(synthetic_source["source_id"], 2022)]
    assert len(candidates) == 6

    # Replay pins the original inputs even after a new source is preserved.
    invoke("ingest", str(ROOT / "tests/fixtures/synthetic.html"), "--provenance", "synthetic")
    expanded = invoke("index-collection")
    assert before != expanded
    assert invoke("replay-collection", str(record)) == answer
    run["snapshot"]["extraction_version"] = "different-parser-version"
    altered = tmp_path / "altered.json"
    altered.write_text(json.dumps(run), encoding="utf-8")
    assert main(["replay-collection", str(altered), *store_args]) == 1
    assert "saved collection snapshot does not match" in capsys.readouterr().err

    # A newer evidence version bypasses the older cached extraction.
    monkeypatch.setattr("frag.verification.EVIDENCE_VERSION", "updated-evidence")
    monkeypatch.setattr("frag.store.RESULT_VERSION", "updated-extraction")
    refreshed = invoke("index-collection")
    assert refreshed["snapshot_id"] != expanded["snapshot_id"]
    assert refreshed["fact_ids"] == expanded["fact_ids"]
    assert refreshed["parents"] == expanded["parents"]
    updated = invoke("ask-collection", "MSFT FY2022 revenue")
    assert updated["citations"] != answer["citations"]
    assert updated["fact"] == (run["outcome"]["fact"] | {"evidence_version": "updated-evidence"})


def test_collection_browser_api_opens_original_cell(tmp_path: Path) -> None:
    from frag.store import SourceStore
    from frag.web import create_app

    store = SourceStore(tmp_path / "store")
    original = gzip.decompress(ANCHOR.read_bytes())
    source = store.ingest_bytes(original, provenance="local_original")
    client = create_app(store, tmp_path).test_client()
    path = "/api/collection/lookup"
    question = {"question": "What was Microsoft FY2023 revenue?"}
    assert client.post(path, json=question).status_code == 403
    answer = client.post(path, json=question, headers={"X-Frag-Ask": "1"})
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "no-store"
    data = answer.get_json()
    assert data["fact"]["normalized_amount"] == "211915000000"
    href = data["citations"][0]["href"]
    excerpt = client.get(href)
    assert excerpt.status_code == 200
    assert excerpt.mimetype == "text/plain"
    body = excerpt.get_data(as_text=True)
    assert source["source_hash"] in body
    assert body.endswith("Total revenue\n2023\n(In millions, except per share amounts)\n211,915\n")
    assert client.get(href.rsplit("/", 1)[0] + "/stale-version").status_code == 404
