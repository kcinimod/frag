# Issue #5 SEC acquisition

The first live request returned HTTP 403 on November 19, 2026 UTC and saved no
response. That request used the public FRAG project URL as the contact identifier.
A diagnostic request returned the SEC's “Undeclared Automated Tool” page.
Acquisition succeeded at 17:03:12 UTC that day with a name and monitored email
in the user agent. The filing identity and primary document are listed in the
[SEC filing index](https://www.sec.gov/Archives/edgar/data/789019/000095017023035122/0000950170-23-035122-index.htm).

The implementation follows the SEC's guidance to identify scripted requests
and minimize repeat access.
[EDGAR access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
[SEC user-agent guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions)

## Run record

| Workflow | Observed result |
| --- | --- |
| Live SEC acquisition | The CLI preserved 9,963,696 bytes with `sec_download` provenance and source ID `sha256:22b0e75303aab69159ff123688343f00c1f6f6bf1e556787a8390bb1972f3467`. Cached download and inspection returned identical records without a user agent and with socket operations forbidden. |
| Controlled SEC responses | Preserved all 163 synthetic bytes. Offline download reuse and inspect returned the same record with `sec_download` provenance and source ID `sha256:6b6e91d29f4abad0191f2f1702a2263653413c7954893a74fd6aa9200e5d9f80`. This fixture provides workflow evidence. |
| Controlled failures | Retried an HTTP 429 and a transport timeout, stopped after one HTTP 403 and after three HTTP 503 responses, declined a 600-second retry request, rejected a redirect, and reported a corrupted cached original. |
| Local fallback | PowerShell ingest and inspect preserved the 9,963,591-byte retained mirror copy with `local_original` provenance and source ID `sha256:6506060f3f928e31abcbcfe46792ff4e0ae5c60bd9ad40964933c37ac854a9ea`. The Microsoft replay also passed with socket operations forbidden. [Retained-copy verification](VERIFICATION_HANDOFF.md) |

| Validation command | Result |
| --- | --- |
| `uv run --locked --offline pytest -q tests/test_sec_workflow.py` | 7 passed |
| `uv run --locked --offline pytest -q` | 50 passed |
| `uv run --locked --offline mypy` | No issues in 14 files |
| `npm.cmd --prefix web run build` | TypeScript check and Vite build passed |

The PowerShell commands for the controlled cache and local copy are in the
[README](../../README.md#download-and-inspect-the-microsoft-filing).

## Byte comparison and replay

The SEC response differs from the mirror by one 105-byte HTML script element
near the end of the document. Omitting offsets `[9963575, 9963680)` from an
in-memory copy produces a byte-for-byte match with the retained mirror.
The cache preserves the full, unchanged response. The verifier pins the
retained filing's source hash, so FY2022 and FY2023 observations from the
direct response remain provisional. The existing verification applies to
the retained copy.

Use the same store for subsequent cache hits and inspection. An empty store
requires a real contact and SEC access for the initial download.

```powershell
$secStore = 'artifacts/phase01/local-store/sec'
$direct = uv run --locked --offline frag download --store $secStore | ConvertFrom-Json
uv run --locked --offline frag inspect $direct.source_id --store $secStore
```
