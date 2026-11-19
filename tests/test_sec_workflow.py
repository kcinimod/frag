"""Exercise SEC acquisition through the CLI with controlled HTTP responses."""

import io
import json
from email.message import Message
from pathlib import Path
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from frag.cli import main

from test_source_workflow import FIXTURE, invoke, success

SEC_URL = "https://www.sec.gov/Archives/edgar/data/789019/000095017023035122/msft-20230630.htm"
USER_AGENT = "FRAG Integration Test contact@example.invalid"
FIXTURE_HASH = "6b6e91d29f4abad0191f2f1702a2263653413c7954893a74fd6aa9200e5d9f80"


class SyntheticResponse(io.BytesIO):
    status = 200
    code = 200
    msg = "OK"

    def __init__(self) -> None:
        super().__init__(FIXTURE.read_bytes())
        self.headers = Message()
        self.headers["Content-Type"] = "text/html"
        self.headers["Content-Length"] = str(len(self.getvalue()))

    def geturl(self) -> str:
        return SEC_URL

    def info(self) -> Message:
        return self.headers


def test_download_preserves_response_and_inspects_cached_original_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def fetch(handler: object, request: Request) -> SyntheticResponse:
        assert request.full_url == SEC_URL
        assert request.get_header("User-agent") == USER_AGENT
        assert getattr(request, "timeout") > 0
        return SyntheticResponse()

    store = str(tmp_path / "store")
    monkeypatch.setenv("SEC_USER_AGENT", USER_AGENT)
    monkeypatch.setattr("urllib.request.HTTPSHandler.https_open", fetch)
    assert main(["download", "--store", store]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["source_hash"] == FIXTURE_HASH
    assert record["source_id"] == f"sha256:{FIXTURE_HASH}"
    assert Path(record["original_path"]).read_bytes() == FIXTURE.read_bytes()
    assert record["source_url"] == SEC_URL
    assert record["company"] == "Microsoft Corporation"
    assert record["accession"] == "0000950170-23-035122"
    assert record["form"] == "10-K"
    assert record["filing_date"] == "2023-07-27"
    assert record["provenance"]["kind"] == "sec_download"
    assert record["real_source_acceptance"] is False
    monkeypatch.delenv("SEC_USER_AGENT")
    assert success("download", "--store", store) == record
    assert success("inspect", record["source_id"], "--store", store) == record
    assert success("inspect", "--store", store)["source_count"] == 1


def test_download_waits_after_transient_http_and_transport_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    headers = Message()
    headers["Retry-After"] = "3"
    responses: Iterator[Exception | SyntheticResponse] = iter([
        HTTPError(SEC_URL, 429, "Too Many Requests", headers, None),
        URLError(TimeoutError("connection timed out")),
        SyntheticResponse(),
    ])
    delays: list[float] = []

    def fetch(handler: object, request: Request) -> SyntheticResponse:
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setenv("SEC_USER_AGENT", USER_AGENT)
    monkeypatch.setattr("urllib.request.HTTPSHandler.https_open", fetch)
    monkeypatch.setattr("time.sleep", delays.append)
    assert main(["download", "--store", str(tmp_path / "store")]) == 0
    assert delays == [3, 2]
    assert json.loads(capsys.readouterr().out)["source_hash"] == FIXTURE_HASH


@pytest.mark.parametrize(("status", "retry_after", "expected_delays", "diagnostic"), [
    (403, None, [], "after 1 attempt"),
    (503, None, [1, 2], "after 3 attempts"),
    (429, "600", [], "Retry-After exceeds the 10s wait limit"),
])
def test_terminal_download_failure_leaves_local_fallback_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    status: int, retry_after: str | None, expected_delays: list[float], diagnostic: str,
) -> None:
    attempts = 0
    delays: list[float] = []

    def fetch(handler: object, request: Request) -> SyntheticResponse:
        nonlocal attempts
        attempts += 1
        headers = Message()
        if retry_after is not None:
            headers["Retry-After"] = retry_after
        raise HTTPError(SEC_URL, status, "Controlled HTTP failure", headers, None)

    monkeypatch.setenv("SEC_USER_AGENT", USER_AGENT)
    monkeypatch.setattr("urllib.request.HTTPSHandler.https_open", fetch)
    monkeypatch.setattr("time.sleep", delays.append)
    store = tmp_path / "store"
    assert main(["download", "--store", str(store)]) == 1
    result = capsys.readouterr()
    assert not result.out
    message = json.loads(result.err)["error"]
    assert f"HTTP {status}" in message
    assert diagnostic in message
    assert "frag ingest" in message
    assert attempts == len(expected_delays) + 1
    assert delays == expected_delays
    assert not store.exists()
    record = success("ingest", str(FIXTURE), "--store", str(store), "--provenance", "synthetic")
    assert record["source_hash"] == FIXTURE_HASH
    assert record["provenance"]["kind"] == "synthetic"


def test_download_cache_detects_corrupted_bytes_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", USER_AGENT)
    monkeypatch.setattr("urllib.request.HTTPSHandler.https_open", lambda *args: SyntheticResponse())
    store = str(tmp_path / "store")
    assert main(["download", "--store", store]) == 0
    record = json.loads(capsys.readouterr().out)
    Path(record["original_path"]).write_bytes(b"corrupted")
    bad_cache = invoke("download", "--store", store)
    assert bad_cache.returncode == 1
    assert "hash mismatch" in json.loads(bad_cache.stderr)["error"]


def test_download_does_not_follow_a_redirect_from_the_selected_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    class RedirectResponse(SyntheticResponse):
        status = 302
        code = 302
        msg = "Found"

    def fetch(handler: object, request: Request) -> SyntheticResponse:
        assert request.full_url == SEC_URL
        response = RedirectResponse()
        response.headers["Location"] = "https://redirect.example.invalid/unexpected"
        return response

    monkeypatch.setenv("SEC_USER_AGENT", USER_AGENT)
    monkeypatch.setattr("urllib.request.HTTPSHandler.https_open", fetch)
    store = tmp_path / "store"
    assert main(["download", "--store", str(store)]) == 1
    assert "HTTP 302" in json.loads(capsys.readouterr().err)["error"]
    assert not store.exists()
