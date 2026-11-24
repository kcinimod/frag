# Phase 5 SEC development baseline

Issue #27 freezes the filing-scoped revenue workflow before Phase 5 changes.
The baseline uses production commit `e0ca1ec304880290b03ebb193cecb88000727c0b`
and its Qwen2.5-0.5B-Instruct Q4_K_M planner. The snapshot exports that commit
directly to isolate the measurement from working-tree changes.
[Issue #27](https://github.com/kcinimod/frag/issues/27)

[Issue #28 shared year-end lookup checkpoint](UNSEEN_LOOKUP.md)

## Fixed cohort and evidence

The 15 questions cover lookup and growth across six issuer families and
seven domestic 10-Ks. The four new issuer families have three statement
layouts. The custody check compared CIKs against the Phase 4 runner
manifest after verifying the archive digest from its receipt. It read only
the CIK field from reserved sources and found zero overlap. All six CIKs
are reserved from fresh holdout selection. [Development CIKs](custody.json)

| Issuer and report | Revenue row and fiscal columns | Prior to current, USD millions | Reported growth |
| --- | --- | ---: | ---: |
| Microsoft FY2023 control | Total revenue, June 30 and separate descending years, scale in table | 198,270 to 211,915 | 6.88% |
| Apple FY2023 control | Total net sales, full dates descending, scale above table | 394,328 to 383,285 | -2.80% |
| Amazon FY2023 | Total net sales, December 31 and separate ascending years, scale above table | 513,983 to 574,785 | 11.83% |
| Walmart FY2024 | Total revenues, January 31 and separate descending years, scale in table | 611,289 to 648,125 | 6.03% |
| Alphabet FY2023 | Revenues, December 31 and separate ascending years, scale above table | 282,836 to 307,394 | 8.68% |
| Intel FY2023 | Net revenue, full dates descending, scale above table | 63,054 to 54,228 | -14.00% |

- Apple FY2020 is absent from the FY2023 statement's annual series. The
  growth question asks for FY2020 to FY2023 and can retain the FY2023 operand.
- Apple's FY2024 filing provides an independently answerable lookup with
  a specific pre-change verification gap. The visible USD 391,035 million
  observation and inline XBRL agree. The reviewed production reference
  covers the FY2023 original.
- The Intel equal-length question requires a grounded abstention. Note 1
  establishes that FY2022 lasted 53 weeks and FY2023 lasted 52. The
  ordinary as-reported growth question uses these two actual totals and
  requires the period-length caveat.

Expected values were read from the visible consolidated statements and
checked against the same original's inline fact, dimensional scope,
reporting dates, currency, and scale. The reference pins statement, header,
cell, context, unit, and applicable disclosure byte spans. The control
disclosures reuse the previously reviewed spans. Expected growth was
cross-checked from the transcribed operands before running the model.
The source manifest records the canonical SEC URLs and the mirror URLs for
the preserved copies. [Questions and originals](inputs.json) ·
[Expected results](expected.json)

## Measured baseline

Cold and warm passes had the same scores. The live records retain intake
diagnostics, parser and evidence versions, eligible evidence, requests and
proposals, validation results, operation traces, and original citation responses.
[Live evidence](live.json.gz) · [Offline replay](replay.json.gz) ·
[Per-case scores and stages](score.json)

| Measure | Cold | Warm |
| --- | ---: | ---: |
| Numeric accuracy on answerable cases | 4/13 | 4/13 |
| Original citation support among emitted answers | 2/4 | 2/4 |
| Original citation support on answerable cases | 2/13 | 2/13 |
| Numeric answer coverage | 4/15 | 4/15 |
| Grounded abstention | 1/2 | 1/2 |
| End-to-end completion | 3/15 | 3/15 |
| Offline result and citation matches | 15/15 | 15/15 |
| Question latency, median and range | 40.2 ms (9.1–6,309.6) | 54.5 ms (10.6–8,241.0) |
| Planner latency with a request, median over seven cases | 1,894.9 ms | 2,167.9 ms |

- Microsoft and Apple FY2023 supplied all four correct numeric answers.
  Apple's lookup and growth citations passed the original-cell, currency,
  scale, and disclosure checks. Apple's absent-year answer also passed
  and retained the FY2023 original citations. Microsoft's amount excerpts
  omit currency evidence, and its lookup links only the statement cell.
- The four new issuers produced zero extracted annual revenue facts. Amazon
  reached the dated statement parser and stopped at its shared-date header.
  Walmart, Alphabet, and Intel fell back to the Microsoft-specific extractor.
  The four ordinary growth responses flagged both requested years as missing
  even though both observations are present.
- Apple's FY2024 observation was extracted with the correct period, amount,
  and cell locator. It remained provisional, and the lookup reported an
  evidence gap before calling the planner. The Intel equal-length question
  returned generic clarification before retrieval or planning.

Cold means the first question after a fresh planner process reports healthy.
Warm immediately repeats that question using the same process and store.
The frozen request disables prompt caching. Question latency includes
opening all returned citation routes and excludes ingestion and planner
startup. Seven cases sent planner requests per pass, so the all-case
median mainly reflects handling before inference. Planner startup had a
511.2 ms median and ranged from 504.4 to 564.8 ms. Windows peak working
sets were 573.57 MiB for the planner and 87.60 MiB for the Python runner
over its lifetime, including ingestion. Sampled peak NVIDIA device VRAM
was 0 MiB on the RTX 5060 Laptop GPU with offload set to zero. VRAM is a
sampled device-wide measure and the two RAM peaks are per-process high
water marks.

## Reproduce in PowerShell

Run from the repository root with the locked Python environment installed.
The live run requires `nvidia-smi` and the pinned model and Windows llama.cpp
runtime. The required Python and dependency versions and the model and
runtime hashes are in the retained freeze.
[Freeze manifest](freeze.json)

Replay the retained answers with the planner stopped. The snapshot contains
the original questions and filings, and the replay process blocks every
socket connection. The scorer reads the expected file after replay.

```powershell
$ErrorActionPreference = 'Stop'
$repo = (Get-Location).Path
$snapshot = & artifacts/phase05/snapshot.ps1 -Destination (Join-Path 'build' ('phase05-' + [guid]::NewGuid()))
$runner = Join-Path $snapshot 'artifacts/phase05/baseline.py'
$scorer = Join-Path $snapshot 'artifacts/phase05/score.py'
Copy-Item -LiteralPath artifacts/phase05/freeze.json -Destination $snapshot
.venv/Scripts/python.exe -c "import gzip, pathlib, sys; pathlib.Path(sys.argv[2]).write_bytes(gzip.decompress(pathlib.Path(sys.argv[1]).read_bytes()))" artifacts/phase05/live.json.gz "$snapshot/live.json"
if ($LASTEXITCODE -ne 0) { throw 'Could not unpack the recorded live run.' }
.venv/Scripts/python.exe $runner replay --data $snapshot --freeze "$snapshot/freeze.json" --work "$snapshot/replay" --live "$snapshot/live.json"
if ($LASTEXITCODE -ne 0) { throw 'Offline replay failed.' }
.venv/Scripts/python.exe $scorer $repo "$snapshot/live.json" "$snapshot/replay/report.json" "$snapshot/score.json"
if ($LASTEXITCODE -ne 0) { throw 'Scoring failed.' }
```

To take new live measurements, create a fresh snapshot with the same setup
commands through `$scorer` above. The exported setup script installs the
frozen planner into the snapshot. It reuses matching cached downloads.
The retained freeze uses dedicated IPv4 loopback port 18089.

```powershell
Copy-Item -LiteralPath artifacts/phase05/freeze.json -Destination $snapshot
$model = New-Item -ItemType Directory -Path "$snapshot/.frag-model"
foreach ($name in @('model.gguf', 'runtime.zip')) {
    if (Test-Path -LiteralPath ".frag-model/$name") {
        Copy-Item -LiteralPath ".frag-model/$name" -Destination $model.FullName
    }
}
& "$snapshot/scripts/setup-local-model.ps1"
.venv/Scripts/python.exe $runner live --data $snapshot --freeze "$snapshot/freeze.json" --model $model.FullName --work "$snapshot/live"
if ($LASTEXITCODE -ne 0) { throw 'Live run failed.' }
.venv/Scripts/python.exe $runner replay --data $snapshot --freeze "$snapshot/freeze.json" --work "$snapshot/replay" --live "$snapshot/live/report.json"
if ($LASTEXITCODE -ne 0) { throw 'Offline replay failed.' }
.venv/Scripts/python.exe $scorer $repo "$snapshot/live/report.json" "$snapshot/replay/report.json" "$snapshot/score.json"
if ($LASTEXITCODE -ne 0) { throw 'Scoring failed.' }
```
