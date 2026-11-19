"""Acquire the selected Microsoft filing through the SEC EDGAR Archives."""

import http.client
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import IO, Any
from urllib import error, request

from frag.store import SourceError, SourceMetadata, SourceStore

FILING_URL = "https://www.sec.gov/Archives/edgar/data/789019/000095017023035122/msft-20230630.htm"
FILING_METADATA = SourceMetadata(
    company="Microsoft Corporation",
    accession="0000950170-23-035122",
    form="10-K",
    filing_date="2023-07-27",
    source_url=FILING_URL,
)
ATTEMPTS = 3
REQUEST_TIMEOUT_SECONDS = 15
MAX_BACKOFF_SECONDS = 10
MAX_FILING_BYTES = 32 * 1024 * 1024
RETRYABLE_HTTP_STATUS = {408, 429, 500, 502, 503, 504}


class _RejectRedirects(request.HTTPRedirectHandler):
    def redirect_request(
        self, req: request.Request, fp: IO[bytes], code: int, msg: str,
        headers: http.client.HTTPMessage, newurl: str,
    ) -> None:
        # Keep the identifying header and retries confined to the selected URL.
        return None


def download_microsoft_filing(store: SourceStore, user_agent: str | None) -> dict[str, Any]:
    cached = store.inspect_download(FILING_URL)
    if cached is not None:
        return cached
    if not user_agent or not user_agent.strip() or not (user_agent.isascii() and user_agent.isprintable()):
        raise SourceError("Set SEC_USER_AGENT to your organization or project name and contact information.")
    filing_request = request.Request(
        FILING_URL, headers={"User-Agent": user_agent.strip(), "Accept-Encoding": "identity"},
    )
    original = _fetch_filing(filing_request)
    return store.ingest_bytes(original, provenance="sec_download", metadata=FILING_METADATA)


def _fetch_filing(filing_request: request.Request) -> bytes:
    opener = request.build_opener(_RejectRedirects())
    for attempt in range(1, ATTEMPTS + 1):
        delay: float = 2 ** (attempt - 1)
        try:
            with opener.open(filing_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                if response.status != 200 or response.geturl() != FILING_URL:
                    raise SourceError(f"Unexpected SEC response (HTTP {response.status} or redirected URL).")
                if response.headers.get_content_type() not in {"text/html", "application/xhtml+xml"}:
                    raise SourceError("The SEC response did not contain HTML.")
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise SourceError("The SEC response used an unexpected content encoding.")
                original: bytes = response.read(MAX_FILING_BYTES + 1)
                if not original or len(original) > MAX_FILING_BYTES:
                    raise SourceError("The SEC response was empty or exceeded 32 MiB.")
                length = response.headers.get("Content-Length")
                if length is not None and length != str(len(original)):
                    raise http.client.IncompleteRead(original)
                return original
        except error.HTTPError as exc:
            exc.close()
            detail = f"HTTP {exc.code} {exc.reason}"
            delay = max(delay, _retry_after_seconds(exc.headers.get("Retry-After")))
            retryable = exc.code in RETRYABLE_HTTP_STATUS
        except (OSError, http.client.HTTPException) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            retryable = True
        except SourceError as exc:
            detail = str(exc)
            retryable = False
        if not retryable or attempt == ATTEMPTS or delay > MAX_BACKOFF_SECONDS:
            if retryable and delay > MAX_BACKOFF_SECONDS and attempt < ATTEMPTS:
                detail += f". Retry-After exceeds the {MAX_BACKOFF_SECONDS}s wait limit"
            attempts = "attempt" if attempt == 1 else "attempts"
            raise SourceError(
                f"SEC download failed after {attempt} {attempts} for {FILING_URL}: {detail}. "
                "Use 'frag ingest' with locally supplied original HTML if available."
            )
        time.sleep(delay)
    raise AssertionError("SEC acquisition attempt limit must be positive.")


def _retry_after_seconds(value: str | None) -> float:
    if value is None:
        return 0
    if value.isascii() and value.isdecimal():
        return float(value)
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    if retry_at.tzinfo is None:
        return 0
    return max(0, (retry_at - datetime.now(timezone.utc)).total_seconds())
