# Phase 3 collection lookup handoff

Issue #13 adds a one-pass annual revenue search to the CLI and the browser.
The collection resolves a company and one fiscal year, then ranks keyword
matches and filters by reporting period, company, metric, consolidated scope,
and evidence verification. Both amounts below use the retained FY2023 10-K.

| Question | Reported revenue | Filing date | Original cell |
| --- | ---: | --- | --- |
| Microsoft FY2022 | USD 198,270 million | 2023-07-27 | HTML line 4403, character 5 |
| Microsoft FY2023 | USD 211,915 million | 2023-07-27 | HTML line 4399, character 5 |

The FY2022 10-K supplies competing provisional observations, including the
FY2022 amount. Its file size, accession, and report date match the SEC index.
The synthetic income statement supplies different-company candidates. The
parser excludes its segment table from the indexed facts, and questions for
segment revenue or guidance receive clarification. The verified amounts
and locators come from the independent Phase 1 inspection.
[FY2022 filing index](https://www.sec.gov/Archives/edgar/data/789019/000156459022026876/0001564590-22-026876-index.htm) · [Phase 1 verification](../phase01/VERIFICATION_HANDOFF.md) · [Corpus and expected answers](corpus-manifest.json)

## Windows PowerShell

From the repository root, prepare dependencies and replay both answers
through the CLI. The replay uses temporary storage by default.

```powershell
uv sync --locked --offline
uv run --locked --offline python artifacts/phase03/collection-replay.py
```

The offline flags use cached dependencies. Use `uv sync --locked` for initial
setup if the required packages are missing from the cache. For the Chrome
smoke check with the built workspace, run the following commands. The first
Playwright setup may also require a run without `--offline`.

```powershell
npm.cmd --prefix web ci
npm.cmd --prefix web run build
uv run --locked --offline --with playwright python artifacts/phase03/collection-replay.py --browser
```

The observed run retained three sources and six facts with stable IDs across
reingestion and reindexing. Both saved runs reproduced the entire outcome
with external access blocked. Ordinary questions left the catalogue and
file inventory unchanged. The browser opened each source citation from
**Ask the collection** and verified the source hash, original row label,
fiscal year, units, and exact cell value.

The isolated staged checkout passed `uv run --locked --offline pytest -q`
with 93 tests and `uv run --locked --offline mypy` with 23 source files checked.

## Snapshot and scope

A collection request builds a content-addressed snapshot from one SQLite
read view of the preserved catalogue. The index uses current parser and
verification versions, checks original hashes and source and parent links,
and keeps each filing's observation and locators. Explicit records retain
ranked candidates and exclusions, selected evidence IDs, and the outcome.
Replay rebuilds the recorded source set even if other filings were added,
and rejects a version or evidence mismatch.

The search supports annual reported consolidated revenue for companies with
eligible verified evidence. The current verification reference covers two
Microsoft observations in the FY2023 10-K. Other supported extractions can
be searched and diagnosed but require independent verification before they
can answer a question.
