# Phase 6 development gate

Issue #42 passed on the 15 opened cases and the 15 earlier regressions. The
candidate was the committed production snapshot
`d5ea2c36af63bb64b30721ceb94cb26236dc4b0a`. The opened cohort and earlier
questions, original bytes, Python dependencies, Qwen2.5-0.5B weights, llama.cpp
runtime, generation settings, and retrieval settings were held to the issue
#36 baseline. The Phase 6 scorer checked the comparison caveats against the
reviewed disclosures and applied the Phase 6 evidence-gap policy. The next
milestone is the separate fresh acceptance evaluation.
[Issue #42](https://github.com/kcinimod/frag/issues/42) · [Frozen baseline](README.md)

| Measure per pass | Opened baseline → candidate | Earlier baseline → candidate |
| --- | ---: | ---: |
| Extracted reviewed observations | 0/19 → 19/19 | 20/21 → 20/21 |
| Verified reviewed observations | 0/19 → 18/19 | 17/21 → 17/21 |
| Correct numeric answers | 0/12 → 12/12 | 12/13 → 12/13 |
| Supported numeric answers | 0/12 → 12/12 | 11/13 → 12/13 |
| Citation support on numeric answers emitted | 0/0 → 12/12 | 11/12 → 12/12 |
| Numeric coverage across all cases | 0/15 → 12/15 | 12/15 → 12/15 |
| Grounded abstentions | 1/3 → 3/3 | 2/2 → 2/2 |
| Completed cases | 1/15 → 15/15 | 13/15 → 14/15 |
| Exact result and citation-set matches in socket-blocked replay | 15/15 → 15/15 | 15/15 → 15/15 |

The opened abstentions were Home Depot unequal fiscal weeks, Coca-Cola's
absent FY2021 with a cited FY2024 companion, and historical GE FY2018. GE's
original shows USD 121,615 million and the workflow retains it as provisional
because the supplied HTML lacks inline XBRL verification. Each observation in
the score carries the reviewed statement and cell byte spans, the amount,
reporting period, currency and scale, and the candidate's classification and
locators.
[Per-case scores and 19-observation audit](gate-score.json)

Every earlier case completed in both passes except Apple FY2024. The intake
extracted the amount and the answer stopped at verification. The retained
diagnostics record source identity conflicts and unresolved applicable
disclosures from Notes 1, 2, and 13. The older Apple lookup, growth, and
absent-year controls passed. Microsoft growth returned 6.88%, and the opened
amount excerpts now include the original `iso4217:USD` measure.
[Earlier live run](gate-earlier-live.json.gz) · [Earlier replay](gate-earlier-replay.json.gz)

| Cohort | Cold median ms (min–max), baseline → candidate | Warm median ms (min–max), baseline → candidate | Windows runner / planner peak working set MiB, baseline → candidate | Peak sampled VRAM MiB, baseline → candidate |
| --- | --- | --- | --- | --- |
| Opened | 20.1 (13.6–62.7) → 1,912.5 (61.8–6,047.6) | 13.9 (12.0–19.6) → 2,143.2 (16.2–8,177.3) | 61.59 / 513.16 → 68.76 / 578.62 | 0 → 0 |
| Earlier | 1,804.2 (29.8–7,167.3) → 1,975.6 (41.1–7,060.8) | 1,782.7 (11.7–8,053.1) → 2,120.1 (16.9–8,135.8) | 88.97 / 578.67 → 88.57 / 578.70 | 0 → 0 |

Cold timing starts with the first question after a fresh planner process is
healthy. Warm timing repeats the same question immediately against that
planner and store. Question latency includes opening the cited excerpts and
excludes intake and planner startup. The opened cohort made 12 planner calls
per pass, up from zero. Windows RAM values are per-process peak working
sets. VRAM is the sampled device-wide peak. The paired per-case record gives
baseline and candidate question latencies, stop stages and abstention reasons,
accuracy, citation support, and coverage for both passes.
[Opened live run](gate-opened-live.json.gz) · [Opened replay](gate-opened-replay.json.gz)

## Filing and collection regressions

Chrome 158.0.8127.37 opened 19 original citation responses across the five
filing controls and matched their socket-blocked excerpts. The collection
replay retained both Microsoft lookups, 6.88% growth, cited partial evidence,
bounded recovery, and stable reindexing. Chrome opened both collection cells
and the original Note 8 disclosure from both full and partial growth.
[Browser and collection run output](gate-regressions.txt)

## Reproduce on Windows

Use the pinned Python environment and Phase 5 custody archives described in the
[baseline setup](README.md#reproduce-on-windows). From the repository root,
replay the retained cold and warm plans with sockets blocked and rescore them
against the reviewed originals. Pass `-Custody` to specify a different copy
of the custody directory. Expect `30/30` matches for each cohort and a
passing `gate-score.json` under the destination.

```powershell
$gate = "build/phase06-gate-replay-$([guid]::NewGuid())"
& artifacts/phase06/development.ps1 -Destination $gate -ReplayRetained
```

To measure fresh cold and warm timings, use the pinned local model and
Windows runtime from the baseline setup. This command also runs offline replay
and scores the result. Startup, question, and intake timings are measured anew.

```powershell
$live = "build/phase06-gate-live-$([guid]::NewGuid())"
& artifacts/phase06/development.ps1 -Destination $live
```

To repeat the filing and collection browser checks against the same source
and UI snapshot, use the replay destination from above and the project's
installed web dependencies. Chrome and cached Playwright are required.

```powershell
$snapshot = (Resolve-Path $gate).Path
New-Item -ItemType Junction -Path "$snapshot/web/node_modules" -Target (Resolve-Path web/node_modules).Path | Out-Null
npm.cmd --prefix "$snapshot/web" run build
$savedPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$snapshot/src"
    uv run --locked --offline --no-sync --with playwright python "$snapshot/artifacts/phase06/replay_grounded_evidence.py"
    uv run --locked --offline --no-sync --with playwright python "$snapshot/artifacts/phase03/collection-replay.py" --growth --bounded --browser --work-dir "$snapshot/collection-validation"
} finally {
    $env:PYTHONPATH = $savedPythonPath
}
```
