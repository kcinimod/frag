# Phase 3 one-pass revenue growth

Issue #14 extends **Ask the collection** and `ask-collection` to reported
consolidated revenue growth. The resolver identifies the company and ordered
fiscal years from the question. The baseline ranks the pinned catalogue once
and selects up to 16 evidence records. An explicit CLI context limit can
reproduce an omission. Selected revenue observations include their cell,
period, and unit locators. Applicable notes and comparison disclosures count
as separate records.

The calculator receives a single filing's verified comparative and current
observations and their selected supporting context. The collection answer
uses deterministic request resolution and calculation. The filing chatbot
continues to validate model-proposed plans through its existing executor.

| Retained run | Observed result | Ask / replay |
| --- | --- | --- |
| [Complete with distractors](growth-baseline/complete-with-distractors.json) | Microsoft FY2022 to FY2023 growth of 6.88%, with a USD 13,645 million increase in the trace. | 13.2 / 13.1 ms |
| [Missing fiscal year](growth-baseline/missing-year.json) | FY2023 revenue of USD 211,915 million with FY2021 listed as missing. | 12.9 / 13.8 ms |
| [Missing required context](growth-baseline/missing-context.json) | Both verified amounts supported. The two-record limit leaves out the comparison and notes, including Note 8. | 14.4 / 11.9 ms |
| [Synthetic incompatible basis](growth-baseline/synthetic-incompatible.json) | Comparison unresolved. Both observations and the reporting-basis disclosure are returned. | 11.5 / 2.9 ms |
| [Synthetic zero baseline](growth-baseline/synthetic-zero.json) | Percentage undefined with USD 12 million absolute change. | 11.5 / 3.0 ms |

Timings are one in-process Windows CLI run after ingestion, including
record writing for the ask and record reading for replay.

The [Phase 1 verification handoff](../phase01/VERIFICATION_HANDOFF.md) records
the independent check of USD 198,270 million and USD 211,915 million at
original HTML lines 4403 and 4399. The percentage is the change of 13,645
million divided by 198,270 million and rounded to two decimal places. The
[corpus manifest](corpus-manifest.json) identifies the preserved FY2023 and
FY2022 filings and different-company synthetic distractor. For the last
two cases, the harness preserves separate synthetic HTML documents and
uses fixture-specific verification in isolated stores. Each fixture's
values and reporting-basis disclosure can be opened through its citations.

## Windows PowerShell replay

Run from the repository root with the locked dependencies installed.

```powershell
$growthRun = Join-Path 'build' ([guid]::NewGuid().ToString())
.venv/Scripts/python.exe artifacts/phase03/collection-replay.py --growth --work-dir $growthRun
$growthStore = Join-Path $growthRun 'store'
.venv/Scripts/frag.exe ask-collection "What was Microsoft's reported consolidated revenue growth from FY2022 to FY2023?" --store $growthStore
.venv/Scripts/frag.exe replay-collection artifacts/phase03/growth-baseline/complete-with-distractors.json --store $growthStore
```

The harness blocks external sockets and DNS, verifies original file hashes,
and compares each fresh CLI run and replay to the retained JSON. Each
record captures the source and index versions, ranked candidates, selected
context, limit, and outcome with its stop reason. The synthetic records
require the harness to prepare their isolated stores.

The Chrome smoke run displayed 6.88% and opened the original Note 8
excerpt. It also reopened both revenue lookup cells.

```powershell
npm.cmd --prefix web run build
uv run --locked --offline --with playwright python artifacts/phase03/collection-replay.py --growth --browser --work-dir (Join-Path 'build' ([guid]::NewGuid().ToString()))
```
