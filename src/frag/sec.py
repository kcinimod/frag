"""Discover and acquire filings through SEC EDGAR."""

import http.client
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import IO, Any
from urllib import error, request

from frag.store import SourceError, SourceMetadata, SourceStore

FILING_URL = "https://www.sec.gov/Archives/edgar/data/789019/000095017023035122/msft-20230630.htm"
TICKER_INDEX_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
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
HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
JSON_TYPES = frozenset({"application/json"})


class _RejectRedirects(request.HTTPRedirectHandler):
    def redirect_request(
        self, req: request.Request, fp: IO[bytes], code: int, msg: str,
        headers: http.client.HTTPMessage, newurl: str,
    ) -> None:
        # Keep the identifying header and retries confined to the selected URL.
        return None


def download_microsoft_filing(store: SourceStore, user_agent: str | None) -> dict[str, Any]:
    return _download_filing(store, FILING_URL, FILING_METADATA, user_agent)


@dataclass(frozen=True)
class FilingMatch:
    cik: str
    company: str
    accession: str
    form: str
    filing_date: str
    report_date: str | None
    source_url: str


def search_edgar_filings(
    company: str, year: str, form: str, user_agent: str | None,
) -> list[FilingMatch]:
    company = company.strip().upper()
    form = form.strip().upper()
    if not re.fullmatch(r"[0-9]{4}", year):
        raise SourceError("Enter a four-digit filing year.")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9 /-]{0,29}", form):
        raise SourceError("Enter a SEC form such as 10-K or 10-Q.")
    numeric = re.fullmatch(r"[0-9]{1,10}", company)
    if not numeric and not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,19}", company):
        raise SourceError("Enter a company ticker such as MSFT or a numeric SEC CIK.")
    agent = _identifying_user_agent(user_agent)
    if numeric:
        cik = int(company)
    else:
        tickers = _fetch_json(TICKER_INDEX_URL, agent)
        cik = next((
            entry["cik_str"] for entry in tickers.values()
            if isinstance(entry, dict) and entry.get("ticker") == company
            and type(entry.get("cik_str")) is int
        ), 0)
    if not 1 <= cik <= 9_999_999_999:
        raise SourceError(f"No company found for {company}. Try its SEC CIK.")

    padded_cik = f"{cik:010d}"
    submissions = _fetch_json(f"{SUBMISSIONS_URL}/CIK{padded_cik}.json", agent)
    name = submissions.get("name")
    filings = submissions.get("filings")
    if not isinstance(name, str) or not name.strip() or not isinstance(filings, dict):
        raise SourceError("SEC EDGAR returned unexpected company filing metadata.")
    matches = _matches(filings.get("recent"), cik, name, year, form)
    history = filings.get("files", [])
    if not isinstance(history, list):
        raise SourceError("SEC EDGAR returned an unexpected filing history.")
    for entry in history:
        if not isinstance(entry, dict):
            continue
        first, last, filename = (entry.get(field) for field in ("filingFrom", "filingTo", "name"))
        if (
            isinstance(first, str) and isinstance(last, str)
            and first[:4] <= year <= last[:4] and isinstance(filename, str)
            and re.fullmatch(rf"CIK{padded_cik}-submissions-[0-9]+\.json", filename)
        ):
            older = _fetch_json(f"{SUBMISSIONS_URL}/{filename}", agent)
            matches.extend(_matches(older, cik, name, year, form))
    unique = {match.accession: match for match in matches}
    return sorted(unique.values(), key=lambda match: (match.filing_date, match.accession), reverse=True)


def _matches(
    rows: Any, cik: int, name: str, year: str, form: str,
) -> list[FilingMatch]:
    if not isinstance(rows, dict):
        raise SourceError("SEC EDGAR returned unexpected filing records.")
    columns: list[list[Any]] = []
    for key in ("form", "filingDate", "reportDate", "accessionNumber", "primaryDocument"):
        column = rows.get(key)
        if not isinstance(column, list):
            raise SourceError("SEC EDGAR returned incomplete filing records.")
        columns.append(column)
    if len({len(column) for column in columns}) != 1:
        raise SourceError("SEC EDGAR returned incomplete filing records.")
    results = []
    for row_form, date, report_date, accession, document in zip(*columns, strict=True):
        if (
            row_form == form and isinstance(date, str)
            and re.fullmatch(rf"{year}-[0-9]{{2}}-[0-9]{{2}}", date)
            and isinstance(accession, str) and re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession)
            and isinstance(document, str) and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]*\.html?", document, re.I)
        ):
            results.append(FilingMatch(
                str(cik), name, accession, form, date,
                report_date if isinstance(report_date, str) and report_date else None,
                f"{ARCHIVES_URL}/{cik}/{accession.replace('-', '')}/{document}",
            ))
    return results


def download_edgar_filing(
    store: SourceStore, match: FilingMatch, user_agent: str | None,
) -> dict[str, Any]:
    metadata = SourceMetadata(
        company=match.company, accession=match.accession, form=match.form,
        filing_date=match.filing_date, source_url=match.source_url,
    )
    return _download_filing(store, match.source_url, metadata, user_agent)


def _download_filing(
    store: SourceStore, url: str, metadata: SourceMetadata, user_agent: str | None,
) -> dict[str, Any]:
    cached = store.inspect_download(url)
    if cached is not None:
        return cached
    original = _fetch_response(url, _identifying_user_agent(user_agent), HTML_TYPES)
    return store.ingest_bytes(original, provenance="sec_download", metadata=metadata)


def _identifying_user_agent(user_agent: str | None) -> str:
    if not user_agent or not user_agent.strip() or not (user_agent.isascii() and user_agent.isprintable()):
        raise SourceError("Set SEC_USER_AGENT to your organization or project name and contact information.")
    return user_agent.strip()


def _fetch_json(url: str, user_agent: str) -> dict[str, Any]:
    try:
        payload = json.loads(_fetch_response(url, user_agent, JSON_TYPES))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SourceError(f"SEC EDGAR returned invalid JSON for {url}.") from exc
    if not isinstance(payload, dict):
        raise SourceError(f"SEC EDGAR returned unexpected JSON for {url}.")
    return payload


def _fetch_response(url: str, user_agent: str, content_types: frozenset[str]) -> bytes:
    sec_request = request.Request(
        url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"},
    )
    opener = request.build_opener(_RejectRedirects())
    for attempt in range(1, ATTEMPTS + 1):
        delay: float = 2 ** (attempt - 1)
        try:
            with opener.open(sec_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                if response.status != 200 or response.geturl() != url:
                    raise SourceError(f"Unexpected SEC response (HTTP {response.status} or redirected URL).")
                if response.headers.get_content_type() not in content_types:
                    raise SourceError("The SEC response had an unexpected content type.")
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
                f"SEC download failed after {attempt} {attempts} for {url}: {detail}. "
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
