# Issue #5 SEC acquisition

The live request to the selected SEC Archives URL returned HTTP 403
Forbidden on November 19, 2026 UTC. The CLI exited with code 1 after one
attempt, printed the attempted URL and the local-ingest fallback, and saved
no direct response. The attempt used the public FRAG project URL as its
contact identifier. Direct acquisition and a byte comparison with the retained
copy remain outstanding. The filing identity and primary document are listed
in the [SEC filing index](https://www.sec.gov/Archives/edgar/data/789019/000095017023035122/0000950170-23-035122-index.htm).

The implementation follows the SEC's guidance to identify scripted requests
and minimize repeat access.
[EDGAR access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
[SEC user-agent guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions)

## Run record

| Workflow | Observed result |
| --- | --- |
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

## Remaining direct-source check

Set a monitored SEC contact address and run against the direct-source store
from a connection with access to SEC EDGAR. Compare the resulting
`source_hash` with the retained copy's ID above and record the result.

```powershell
$env:SEC_USER_AGENT = 'Your Organization contact@your-domain.example'
uv run --locked --offline frag download --store artifacts/phase01/local-store/sec
```
