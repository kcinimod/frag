# FinQA public test comparison

Issue #21 evaluates the 1,147 IDs in the pinned official public test
split in file order. Both modes use the configuration frozen on dev,
with zero demonstrations and one attempt per question. The annotated
mode supplies excerpts selected by benchmark annotations. The retrieved
mode uses keyword retrieval over the question's report. Review the
annotated-evidence diagnostic separately when interpreting the paired
results. [Frozen protocol and dev measurements](FINQA_COMPARISON.md)

## Public test results

The November 23, 2026 Windows run recorded all 2,294 outcomes and
replayed them offline with the pinned scorer. An interruption during the
annotated pass exercised resume on the real checkpoint. The resumed
run preserved the same configuration and completed both modes.
[Replayable per-question report](finqa-public-test-report.json.gz)

| Outcome across 1,147 questions per mode | Annotated-evidence diagnostic | Retrieved evidence |
| --- | ---: | ---: |
| Outcomes saved and replayed | 1,147 | 1,147 |
| Internal execution answer matches | 30 (2.62%) | 14 (1.22%) |
| Executed with an incorrect answer | 221 | 257 |
| Invalid plans | 891 | 861 |
| Execution failures | 4 | 7 |
| Abstentions | 1 | 7 |
| Model timeouts | 0 | 1 |
| Pinned evaluator execution matches observed | 29 | 13 |
| Pinned evaluator symbolic program matches observed | 22 | 4 |
| Scorer parity | Unresolved | Unresolved |

The internal paired outcomes were 5 correct in both modes, 1,108
incorrect in both, 9 improved with retrieval, and 25 regressed with
retrieval. Retrieval left out annotated evidence during ranking on 93
questions and during context selection on 63 questions. The report retains
the affected question IDs, locators, and exact planner inputs.

The pinned evaluator could not represent proposed table-row labels
containing parentheses for 3 annotated-evidence outcomes and 9
retrieved-evidence outcomes. The scoring adapter submitted EOF-only
predictions for those programs. One case per mode then differed from
the internal execution match. The evaluator's per-question and aggregate
totals reconciled in both modes. The execution and program counts are
reported as internal because translation parity remains unresolved.
See each mode's `scores.cases` for the affected IDs and reasons.

Recorded question elapsed times summed to 5,805.193 seconds for
annotated evidence and 14,094.715 seconds for retrieved evidence. The
saved report's SHA-256 is
`1217e5b685e658f2136b25fb9693dafee0deecff89b8f8bf1198a079648c8fb6`.

## Run, resume, and inspect on Windows

Keep the pinned `test.json` and `evaluate.py` under `build/finqa`.
The cache and scoring environment are prepared with the commands in the
dev diagnostic. The CLI validates the split digest and requires the exact
dev model configuration. Inference uses the pinned runtime archive,
executable, DLLs and weights under `.frag-model`.
[Cache and scorer setup](FINQA_DIAGNOSTIC.md#fresh-run-on-windows)
[Runtime setup](FINQA_COMPARISON.md#run-and-replay-on-windows)

Run from the repository root in Windows PowerShell. Use the same
checkpoint path to resume an interrupted run. The checkpoint commits
each completed outcome by evidence mode and question ID. Resume skips
those IDs and starts at the first unfinished question in each mode. Model
timeouts, invalid plans, execution failures, and abstentions count as
completed outcomes. A question interrupted before its outcome commits
is eligible for retry. Run one operator process per checkpoint.

```powershell
$cache = 'build/finqa'
$checkpoint = Join-Path $cache 'public-test.sqlite'
build/finqa-venv/Scripts/python.exe -m frag.finqa_test run $cache $checkpoint
```

Run the status command in a second PowerShell window while inference runs.
It shows per-mode coverage, recorded outcome counts, and the internal
transitions for IDs completed in both modes.

```powershell
$cache = 'build/finqa'
$checkpoint = Join-Path $cache 'public-test.sqlite'
build/finqa-venv/Scripts/python.exe -m frag.finqa_test status $cache $checkpoint
```

## Score and replay offline

Score after coverage reaches 1,147 in each mode. Use a fresh report
filename when scoring again. Replay checks every saved question,
reference, evidence selection, planner request, proposal, execution,
and score against the pinned inputs without starting a model.

```powershell
$env:TEMP = (Resolve-Path build).Path
$env:TMP = $env:TEMP
$cache = 'build/finqa'
$checkpoint = Join-Path $cache 'public-test.sqlite'
$report = 'artifacts/phase04/finqa-public-test-report.json.gz'
build/finqa-venv/Scripts/python.exe -m frag.finqa_test score $cache $checkpoint $report
build/finqa-venv/Scripts/python.exe -m frag.finqa_test replay $cache $report
```

The report pairs each ID's deterministic execution outcome across the
two modes in `summary.cases`. `answer_transitions` counts retrieval
improvements and regressions, and `coverage` gives the expected and
completed counts. Each mode's `scores` record contains its upstream
predictions, execution and symbolic program matches, and scoring
discrepancies. The summary labels upstream scores official only when the
frozen runtime, complete accounting, and parity in both modes have been
verified. Until then any counts are internal.

The records retain FinQA excerpts under the [MIT license](FINQA_LICENSE.txt).
