"""Exercise the public browser API and CLI against the same local store."""

import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request

import pytest

from frag.cli import main
from frag.store import SourceStore
from frag.web import create_app

from test_sec_workflow import FIXTURE_HASH, SEC_URL, USER_AGENT, SyntheticResponse
from test_source_workflow import FIXTURE


def test_cli_and_browser_api_share_preserved_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "store"
    client = create_app(SourceStore(root), tmp_path).test_client()
    assert client.get("/api/sources").json == {"source_count": 0, "sources": []}
    assert not root.exists()

    fixture = Path(__file__).parent / "fixtures" / "synthetic.html"
    assert main(["ingest", str(fixture), "--store", str(root), "--provenance", "synthetic"]) == 0
    local = json.loads(capsys.readouterr().out)
    assert client.get(f"/api/sources/{local['source_id']}").json == local

    original = b"<html>Synthetic browser fixture\r\n\xff</html>"

    def upload(company: str) -> tuple[int, dict[str, object]]:
        response = client.post(
            "/api/sources", headers={"X-Frag-Upload": "1"},
            data={"file": (io.BytesIO(original), "synthetic.html"),
                  "provenance": "synthetic", "company": company},
        )
        result: dict[str, object] = response.get_json()
        return response.status_code, result

    status, saved = upload("Synthetic browser source")
    assert status == 200
    assert saved["source_hash"] == hashlib.sha256(original).hexdigest()
    assert saved["source_url"] is None
    assert saved["provenance"]["upload_name"] == "synthetic.html"  # type: ignore[index]
    assert saved["real_source_acceptance"] is False
    assert upload("Synthetic browser source") == (200, saved)
    assert upload("Conflicting company")[0] == 409
    assert client.get("/api/sources").get_json()["source_count"] == 2
    assert main(["inspect", str(saved["source_id"]), "--store", str(root)]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record == saved
    assert Path(record["original_path"]).read_bytes() == original


def test_upload_requires_local_form_and_explicit_provenance(tmp_path: Path) -> None:
    root = tmp_path / "store"
    client = create_app(SourceStore(root), tmp_path).test_client()
    assert client.post("/api/sources").status_code == 403
    response = client.post(
        "/api/sources", headers={"X-Frag-Upload": "1"},
        data={"file": (io.BytesIO(b"<p>Synthetic</p>"), "synthetic.html")},
    )
    assert response.status_code == 400
    assert "provenance" in response.get_json()["error"]
    assert not root.exists()


def test_browser_can_download_and_reopen_the_cached_filing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "store"
    client = create_app(SourceStore(root), tmp_path).test_client()
    route = "/api/sources/download"
    headers = {"X-Frag-Download": "1"}
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    assert client.post(route).status_code == 403
    missing_agent = client.post(route, headers=headers)
    assert missing_agent.status_code == 400
    assert "SEC_USER_AGENT" in missing_agent.get_json()["error"]
    assert not root.exists()

    def fetch(handler: object, request: Request) -> SyntheticResponse:
        assert request.full_url == SEC_URL
        assert request.get_header("User-agent") == USER_AGENT
        return SyntheticResponse()

    monkeypatch.setenv("SEC_USER_AGENT", USER_AGENT)
    monkeypatch.setattr("urllib.request.HTTPSHandler.https_open", fetch)
    response = client.post(route, headers=headers)
    assert response.status_code == 200
    record = response.get_json()
    assert record["source_hash"] == FIXTURE_HASH
    assert record["provenance"]["kind"] == "sec_download"
    assert Path(record["original_path"]).read_bytes() == FIXTURE.read_bytes()

    def forbid_request(handler: object, request: Request) -> SyntheticResponse:
        pytest.fail("A cached filing must not make a request to the SEC.")

    monkeypatch.delenv("SEC_USER_AGENT")
    monkeypatch.setattr("urllib.request.HTTPSHandler.https_open", forbid_request)
    assert client.post(route, headers=headers).get_json() == record
    assert client.get("/api/sources").get_json() == {"source_count": 1, "sources": [record]}
    assert main(["inspect", record["source_id"], "--store", str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == record


def test_browser_searches_company_history_by_year_and_form_and_downloads_selected_filing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = create_app(SourceStore(tmp_path / "store"), tmp_path).test_client()
    search = "/api/filings/search"
    download = "/api/sources/download"
    headers = {"X-Frag-Download": "1"}
    tickers_url = "https://www.sec.gov/files/company_tickers.json"
    submissions_url = "https://data.sec.gov/submissions/CIK0000123456.json"
    history_url = "https://data.sec.gov/submissions/CIK0000123456-submissions-001.json"
    filing_url = "https://www.sec.gov/Archives/edgar/data/123456/000012345624000003/first-quarter.htm"
    payloads = {
        tickers_url: {"0": {"ticker": "ACME", "cik_str": 123456}},
        submissions_url: {"name": "Synthetic ACME", "filings": {
            "recent": {
                "form": ["10-Q"], "filingDate": ["2025-05-01"], "reportDate": ["2025-03-31"],
                "accessionNumber": ["0000123456-25-000008"], "primaryDocument": ["recent.htm"],
            },
            "files": [
                {"name": "CIK0000123456-submissions-001.json", "filingFrom": "2024-01-01", "filingTo": "2024-12-31"},
                {"name": "CIK0000123456-submissions-002.json", "filingFrom": "2023-01-01", "filingTo": "2023-12-31"},
            ],
        }},
        history_url: {
            "form": ["10-Q", "10-K", "10-Q"],
            "filingDate": ["2024-08-01", "2024-02-20", "2024-05-01"],
            "reportDate": ["2024-06-30", "2023-12-31", "2024-03-31"],
            "accessionNumber": ["0000123456-24-000004", "0000123456-24-000002", "0000123456-24-000003"],
            "primaryDocument": ["second-quarter.htm", "annual.htm", "first-quarter.htm"],
        },
    }
    requests: list[str] = []

    def fetch(handler: object, request: Request) -> SyntheticResponse:
        assert request.get_header("User-agent") == USER_AGENT
        url = request.full_url
        requests.append(url)
        if url == filing_url:
            return SyntheticResponse(url=url)
        return SyntheticResponse(json.dumps(payloads[url]).encode(), url=url, content_type="application/json")

    monkeypatch.setenv("SEC_USER_AGENT", USER_AGENT)
    monkeypatch.setattr("urllib.request.HTTPSHandler.https_open", fetch)

    filters = {"company": " acme ", "year": "2024", "form": "10-Q"}
    assert client.post(search, json=filters).status_code == 403
    invalid = client.post(search, headers=headers, json={**filters, "company": "https://example.invalid"})
    assert invalid.status_code == 400
    assert requests == []
    unknown = client.post(search, headers=headers, json={**filters, "company": "UNKNOWN"})
    assert unknown.status_code == 400
    assert "No company found" in unknown.get_json()["error"]
    requests.clear()

    results = client.post(search, headers=headers, json=filters)
    assert results.status_code == 200
    filings = results.get_json()["filings"]
    assert [item["report_date"] for item in filings] == ["2024-06-30", "2024-03-31"]
    assert requests == [tickers_url, submissions_url, history_url]
    assert client.get("/api/sources").get_json()["source_count"] == 0

    requests.clear()
    selected = {**filters, "company": filings[1]["cik"], "accession": filings[1]["accession"]}
    response = client.post(download, headers=headers, json=selected)
    assert response.status_code == 200
    record = response.get_json()
    assert record["company"] == "Synthetic ACME"
    assert record["form"] == "10-Q"
    assert record["filing_date"] == "2024-05-01"
    assert record["source_url"] == filing_url
    assert record["source_hash"] == FIXTURE_HASH
    assert record["facts"] == []
    assert requests == [submissions_url, history_url, filing_url]

    requests.clear()
    repeat = client.post(download, headers=headers, json=selected)
    assert repeat.get_json() == record
    assert requests == [submissions_url, history_url]
    assert client.get("/api/sources").get_json()["source_count"] == 1
