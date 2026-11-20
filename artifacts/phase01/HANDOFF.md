# Phase 1 handoff

The acceptance checks for [issue #6](https://github.com/kcinimod/frag/issues/6)
passed for Microsoft's preserved FY2023 Form 10-K. The SEC index identifies
accession `0000950170-23-035122`, CIK `0000789019`, and the July 27, 2023 filing
date. [SEC filing index](https://www.sec.gov/Archives/edgar/data/789019/000095017023035122/0000950170-23-035122-index.htm)

| Observation | Annual reporting period | Reported USD millions | Status |
| --- | --- | ---: | --- |
| FY2022 comparative | 2021-07-01 to 2022-06-30 | 198,270 | Verified |
| FY2023 | 2022-07-01 to 2023-06-30 | 211,915 | Verified |

The reviewed cell, visible year header, annual inline XBRL context, USD unit,
scale, and bounded Notes 1, 8, 13, and 19 support each observation. Microsoft's
published income statements independently corroborate the totals.
[Original HTML inspection](VERIFICATION_HANDOFF.md)
[Microsoft income statements](https://www.microsoft.com/investor/reports/ar23/index.html#income-statements)

The periods are compatible on the reported consolidated US GAAP basis. The
disclosed segment recasts did not affect the consolidated income statements.
FY2022 includes Nuance from March 4, 2022 and FY2023 includes the full year.
The filing also discloses exchange-rate effects. [Machine-readable facts](microsoft-revenue.json)

## Evidence bundle

- [Source manifest](source-manifest.json) records the original's provenance,
  hashes, filing identity, parser and reference versions, and evidence paths.
  The [original HTML archive](originals/msft-20230630.htm.gz) preserves the
  unchanged input bytes separately from the derived records.
- [Independent reference](../../src/frag/microsoft-revenue-reference.json) holds
  the reviewed values, source locators, disclosure ranges, and fingerprints.
- [Validation record](acceptance-validation.txt) contains the commands, run
  output, and stable IDs. Reingestion returned identical source and fact
  records. Replay inspected both facts and checked saved bytes after deleting
  the input, with Python socket operations forbidden in every CLI process.

## Reproduce

From the repository root in Windows PowerShell, with uv installed, run setup
once. The setup step may need network access.

```powershell
uv sync --locked
uv run --locked --offline mypy
uv run --locked --offline pytest -q
```

To ingest and inspect the original through the CLI in a fresh local store:

```powershell
$runDir = Join-Path ([IO.Path]::GetTempPath()) ('frag-phase01-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $runDir | Out-Null
$filingPath = Join-Path $runDir 'msft-20230630.htm'
$filingStore = Join-Path $runDir 'store'
uv run --locked --offline python -c 'import gzip, sys; from pathlib import Path; Path(sys.argv[1]).write_bytes(gzip.decompress(Path(sys.argv[2]).read_bytes()))' $filingPath artifacts/phase01/originals/msft-20230630.htm.gz
if ($LASTEXITCODE -ne 0) { throw 'Could not decompress the retained filing.' }
$filing = uv run --locked --offline frag ingest $filingPath --store $filingStore --provenance local_original --company 'Microsoft Corporation' --accession '0000950170-23-035122' --form '10-K' --filing-date '2023-07-27' --source-url 'https://www.sec.gov/Archives/edgar/data/789019/000095017023035122/msft-20230630.htm' | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Filing ingestion failed.' }
uv run --locked --offline frag inspect $filing.source_id --store $filingStore
```

The replay creates and cleans up its own temporary store. It prints JSON and
returns a nonzero exit code if a check fails.

```powershell
uv run --locked --offline python artifacts/phase01/replay.py --microsoft
```

## Limits and review checkpoint

Verification is scoped to the retained 9,963,591-byte original obtained via
an EDGAR mirror. The live SEC response has a separate hash because of an
additional 105-byte script element. Its cache can be inspected offline and
its observations remain provisional. [Direct SEC acquisition](SEC_ACQUISITION.md)

Phase 1 has no remaining acceptance blockers for the retained original.
Review this bundle before authorizing the next phase. The original source
preservation checkpoint remains in [issue #2's validation record](validation.txt).
