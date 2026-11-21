# Verified revenue growth handoff

The CLI and browser returned **6.88%** for the retained Microsoft FY2023
10-K. Calculation used the verified FY2022 comparative and FY2023 current
observation from the same preserved filing. [Issue #9](https://github.com/kcinimod/frag/issues/9)

| Operand | Annual period | Original USD millions | Normalized USD | Original cell |
| --- | --- | ---: | ---: | --- |
| Prior | 2021-07-01 through 2022-06-30 | 198,270 | 198,270,000,000 | HTML line 4403, character 5 |
| Current | 2022-07-01 through 2023-06-30 | 211,915 | 211,915,000,000 | HTML line 4399, character 5 |

The operation trace recorded a difference of USD 13,645,000,000, an exact
ratio of `2729/39654`, and a typed result of
`{"unit":"percent","value":"6.88"}`. The source hash is
`6506060f3f928e31abcbcfe46792ff4e0ae5c60bd9ad40964933c37ac854a9ea`.
The run used parser `annual-revenue-v4` and evidence reference
`microsoft-fy2023-revenue-v2`. [Phase 1 source record](../phase01/microsoft-revenue.json)

## Reproduce the CLI result

Use Windows PowerShell at the repository root after the README's dependency
setup. The following run used a fresh store under the ignored `build` directory.

```powershell
New-Item -ItemType Directory -Force build | Out-Null
$runDir = Join-Path $PWD ('build/frag-growth-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $runDir | Out-Null
$filingPath = Join-Path $runDir 'msft-20230630.htm'
$filingStore = Join-Path $runDir 'store'
.venv/Scripts/python.exe -c 'import gzip, sys; from pathlib import Path; Path(sys.argv[1]).write_bytes(gzip.decompress(Path(sys.argv[2]).read_bytes()))' $filingPath artifacts/phase01/originals/msft-20230630.htm.gz
if ($LASTEXITCODE -ne 0) { throw 'Could not decompress the retained filing.' }
$source = .venv/Scripts/frag.exe ingest $filingPath --store $filingStore --provenance local_original | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Filing ingestion failed.' }
$growth = .venv/Scripts/frag.exe growth $source.source_id 2022 2023 --store $filingStore | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Growth calculation failed.' }
$growth | Select-Object status, source_id, parser_version, evidence_version, percent, trace | ConvertTo-Json -Depth 5
$growth.operands | Select-Object role, fact_id, raw_amount, normalized_amount, currency, scale | ConvertTo-Json -Depth 4
```

## Offline acceptance

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_growth_workflow.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m mypy --cache-dir build/mypy
npm.cmd --prefix web run build
uv run --locked --offline --with playwright python artifacts/phase01/browser-replay.py
```

- The targeted suite passed seven tests and the full suite passed 59. CLI
  regression subprocesses reject all Python socket operations and calculate
  after the import input is removed. The browser API returned the same JSON as
  the CLI.
- The labeled synthetic cases used a verified zero baseline and USD 12 million
  current revenue. The result had an undefined percentage and a separate USD 12
  million absolute change. Missing, provisional, and incompatible evidence
  produced distinct issue codes and retained the verified current observation.
  An arithmetic-context regression confirms the result is independent of the
  caller's decimal settings.
- Mypy passed for 17 source files. The frontend TypeScript check and production
  build passed.
- Chrome opened the saved filing, calculated 6.88%, and opened the original
  cell for each year, Notes 1, 8, 13, and 19, and all three linked comparison
  disclosures. The replay removed the upload
  input before calculation and verified each excerpt's source hash. It also
  checked that a missing prior year leaves the verified FY2023 amount visible.
  Browser requests were limited to the replay origin and the server rejected
  outbound connections and name resolution outside loopback.

## Limits and review checkpoint

The calculator currently accepts the single annual pair covered by the
selected filing's existing comparison verification. The directly downloaded
SEC copy has a different hash and remains provisional. Reported growth
includes the disclosed effects of currency translation and Nuance's partial
FY2022 consolidation. The citation viewer uses the verified same-line statement
cells and whole-line disclosure ranges from the retained filing.

Project-owner review of this handoff and the offline results is the checkpoint
before starting the local chatbot. [Phase 2 tracker](https://github.com/kcinimod/frag/issues/8)
