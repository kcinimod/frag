# Phase 6 opened-cohort development gate

Issue #53 passed on the original 15 questions from #44. The new run uses
those opened cases for development. The frozen #44 acceptance decision
remains the historical baseline. [#53](https://github.com/kcinimod/frag/issues/53) · [Frozen #44 decision](SEC_ACCEPTANCE.md)

| Measure | Frozen #44 cold | Frozen #44 warm | #53 cold | #53 warm |
| --- | ---: | ---: | ---: | ---: |
| Supported numeric answers | 0/12 | 0/12 | 12/12 | 12/12 |
| Grounded abstentions | 0/3 | 0/3 | 3/3 | 3/3 |
| Socket-blocked result and citation-set matches | 15/15 | 15/15 | 15/15 | 15/15 |
| Supported opened citation responses | 0 | 0 | 61 | 61 |

The scorer matched 21/21 extracted observations to the independent review.
All 18 inline-corroborated observations passed reusable verification with
their applicable notes. NVIDIA FY2016 through FY2018 stayed provisional
because the historical original lacks inline XBRL. The manifest records the
seven original SHA-256 hashes. The score records the original hash, expected
and observed values and locators, and verification outcome for each observation.
[Original manifest](fresh-inputs.json) · [Opened score and audit](continuation-opened-score.json)

## Earlier development and browser regressions

The pinned candidate also repeated all 30 #42 questions. Each pass of the
Phase 5 opened cohort completed 12 supported answers and three grounded
abstentions. Each pass of the earlier development cohort completed 12
supported answers and two grounded abstentions. Apple FY2024 remains an
incomplete lookup because the displayed amount still lacks verification of
applicable disclosures. All 60 results and citation sets matched in offline
replay. [Regression score, original hashes, and per-case stops](continuation-earlier-score.json)
[Phase 5 opened live](continuation-regression-opened-live.json.gz) · [Phase 5 opened replay](continuation-regression-opened-replay.json.gz)
[Earlier live](continuation-regression-earlier-live.json.gz) · [Earlier replay](continuation-regression-earlier-replay.json.gz)

Chrome 158.0.8127.37 opened 19 original citation responses in the five
filing controls and matched the reproduced excerpts. The collection checks
replayed the two Microsoft lookup results, 6.88% growth, partial evidence,
and bounded retrieval. Chrome reopened both Microsoft revenue cells and
Note 8 for supported full and partial growth results.
[Build and browser output](continuation-browser-regressions.txt)

## Opened #44 run details

The production candidate and runner are pinned to
`679ceef3c4b8df34506310b300b98c40eea2940c`. The freeze binds the archived
source, #52 runner, Python 3.12.14, Qwen2.5-0.5B-Instruct Q4_K_M, llama.cpp
runtime, and settings. The initial integrated run produced 12/12 accurate
numeric results and 30/30 exact replays. The original #52 scorer gave full
credit to one grounded abstention per pass. Fourteen cases had original
note excerpts that extended beyond the sealed review's exact spans.

The #53 scoring revision uses a separate, hash-checked review of the
enclosing original excerpts. These include statement note headings, full
accounting-policy paragraphs, and revenue disaggregation tables in Target
Note 3 and Ford Note 4. The Netflix excerpts also contain the next heading
or a page break. The groups of Ford and McDonald's paragraphs each support
two sealed disclosures. The original amount, period, and request references
come from the sealed archives. The score binds the revised scorer and its
dependencies. The scorer requires the pinned review digest and checks each
added span against the original filing and the sealed disclosure it encloses.
The opened gate requires all 12 numeric answers
as well as the extraction and verification counts above.
[Candidate and runtime freeze](continuation-opened-freeze.json) · [Citation review](continuation-reviewed-citations.json)

| Case | Issuer and question | First evidenced outcome in both passes |
| --- | --- | --- |
| P6-01 | Target FY2023 lookup | Complete |
| P6-02 | Target FY2022 to FY2023 reported growth | Complete |
| P6-03 | Netflix FY2024 lookup | Complete |
| P6-04 | Netflix FY2023 to FY2024 reported growth | Complete |
| P6-05 | Ford FY2024 lookup | Complete |
| P6-06 | Ford FY2023 to FY2024 reported growth | Complete |
| P6-07 | NVIDIA FY2025 lookup | Complete |
| P6-08 | NVIDIA FY2024 to FY2025 reported growth | Complete |
| P6-09 | McDonald's FY2024 lookup | Complete |
| P6-10 | McDonald's FY2023 to FY2024 reported growth | Complete |
| P6-11 | Disney FY2024 lookup | Complete |
| P6-12 | Disney FY2023 to FY2024 reported growth | Complete |
| P6-13 | Netflix FY2021 to FY2024 growth | Statement period inventory establishes FY2021 absence, with cited FY2024 revenue |
| P6-14 | NVIDIA FY2018 lookup | Verification stops at missing inline corroboration for the displayed observation |
| P6-15 | Target FY2022 to FY2023 equal-length growth | Comparison compatibility stops at 52 versus 53 weeks, with both verified observations cited |

Median question latency was 1,869.65 ms cold and 2,041.03 ms warm. The ranges
were 38.61 to 6,080.65 ms cold and 13.14 to 7,862.98 ms warm. Peak runner and
planner working sets were 64.40 and 578.83 MiB. Peak device VRAM sampled was
0 MiB. Question latency includes opening the cited evidence and excludes
source ingestion and planner startup. Focused tests overlapped the beginning
of the live measurement. [Live record](continuation-opened-live.json.gz) · [Complete replay record](continuation-opened-replay.json.gz)

## Reproduce on Windows

Run from the repository root with the [pinned Python environment](README.md#reproduce-on-windows)
and the two #44 custody archives. Set `$custody` to their local directory.
To replay the retained run, use a new destination and the saved freeze.

```powershell
$candidate = '679ceef3c4b8df34506310b300b98c40eea2940c'
$phase = 'artifacts/phase06'
$custody = '../FRAG-SEC-Holdout-43'
$run = "build/phase06-opened-replay-$([guid]::NewGuid())"
& "$phase/acceptance.ps1" -Mode Freeze -Destination $run -Continuation -ContinuationRevision $candidate -SavedFreeze "$phase/continuation-opened-freeze.json"
& "$phase/acceptance.ps1" -Mode Replay -Destination $run -Custody $custody -SavedLive "$phase/continuation-opened-live.json.gz"
$live = "$run/runner/retained-live.json"
```

Score with the #53 revision and the separately held scorer archive. Copy the
scorer into the pinned scoring snapshot and normalize its line endings for
the recorded source digest. Expect 30/30 replay matches and a score of 12
supported answers and three grounded abstentions in each pass.

```powershell
$scorer = "$run/scoring/$phase/fresh_score_v2.py"
$scorerSource = [IO.File]::ReadAllText((Resolve-Path "$phase/fresh_score_v2.py").Path).Replace("`r`n", "`n")
[IO.File]::WriteAllText((Resolve-Path $scorer).Path, $scorerSource, [Text.UTF8Encoding]::new($false))
.venv/Scripts/python.exe $scorer "$run/runner/freeze.json" "$run/runner/inputs.zip" `
    "$custody/scorer/expected.zip" $live "$run/runner/replay/report.json" `
    "$run/scoring/opened-score.json" --reviewed-citations "$phase/continuation-reviewed-citations.json"
if ($LASTEXITCODE -ne 0) { throw 'The opened-cohort gate failed.' }
```

To reproduce the recorded score byte for byte, use the same scorer, freeze,
and inputs with both retained reports. Regenerated replay records contain
fresh intake timings.

```powershell
.venv/Scripts/python.exe $scorer "$run/runner/freeze.json" "$run/runner/inputs.zip" `
    "$custody/scorer/expected.zip" "$phase/continuation-opened-live.json.gz" `
    "$phase/continuation-opened-replay.json.gz" "$run/scoring/retained-score.json" `
    --reviewed-citations "$phase/continuation-reviewed-citations.json"
if ($LASTEXITCODE -ne 0) { throw 'The retained opened-cohort score failed.' }
if ((Get-FileHash "$run/scoring/retained-score.json").Hash -ne (Get-FileHash "$phase/continuation-opened-score.json").Hash) {
    throw 'The retained opened-cohort score differs.'
}
```

A fresh timing run requires the [pinned model, runtime and Windows GPU sampler](SEC_ACCEPTANCE.md#reproduce-on-windows).
Use a new destination, then run the scoring block.

```powershell
$run = "build/phase06-opened-live-$([guid]::NewGuid())"
& "$phase/acceptance.ps1" -Mode Freeze -Destination $run -Continuation -ContinuationRevision $candidate
& "$phase/acceptance.ps1" -Mode Live -Destination $run -Custody $custody
& "$phase/acceptance.ps1" -Mode Replay -Destination $run -Custody $custody
$live = "$run/runner/live/report.json"
```

Repeat the earlier development run with the Phase 5 custody archives in
`../FRAG-SEC-Holdout-32`. The destination contains both cohorts' run records
and their combined regression score.

```powershell
$regression = "build/phase06-earlier-$([guid]::NewGuid())"
& "$phase/development.ps1" -Destination $regression -Revision $candidate
```

Build and check the pinned browser snapshot with installed web dependencies,
Chrome, and cached Playwright. [Collection setup](../phase03/COLLECTION_HANDOFF.md)

```powershell
$snapshot = (Resolve-Path $regression).Path
New-Item -ItemType Junction -Path "$snapshot/web/node_modules" -Target (Resolve-Path web/node_modules).Path | Out-Null
npm.cmd --prefix "$snapshot/web" run build
if ($LASTEXITCODE -ne 0) { throw 'Pinned UI build failed.' }
$savedPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$snapshot/src"
    uv run --locked --offline --no-sync --with playwright python "$snapshot/$phase/replay_grounded_evidence.py"
    if ($LASTEXITCODE -ne 0) { throw 'Filing browser checks failed.' }
    uv run --locked --offline --no-sync --with playwright python "$snapshot/artifacts/phase03/collection-replay.py" --growth --bounded --browser --work-dir "$snapshot/collection-validation"
    if ($LASTEXITCODE -ne 0) { throw 'Collection browser checks failed.' }
} finally {
    $env:PYTHONPATH = $savedPythonPath
}
```
