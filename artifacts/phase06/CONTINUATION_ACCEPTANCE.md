# Second fresh Phase 6 SEC acceptance

**Issue #45 decision: failed in both passes.** The #54 cohort produced
0/12 supported numeric answers and 0/3 grounded abstentions in each pass.
All 15 results and citation sets matched in each socket-blocked replay.
Six cases per pass received a blocking `unsupported_abstention_claim` finding.
[Issue #45](https://github.com/kcinimod/frag/issues/45) ·
[Full score and observation audit](continuation-acceptance/score.json)

The pre-release custody recheck matched the final production evidence
inventory to the audited development snapshot. It confirmed zero overlapping
issuer families or originals across 197 lineage accessions, seven originals
from six families, and six layout signatures, two absent from development.
The runner archive remained in custody until the freeze was written at
2026-11-27 08:41:58 UTC. The independently reviewed references stayed in
scorer custody. The freeze binds the protocol, thresholds, evaluation and
production revisions, scorer, dependencies, model weights and binaries,
retrieval, generation settings, and loopback port.
[Protocol](CONTINUATION_PROTOCOL.md) · [Custody receipt](continuation-holdout-receipt.json) ·
[Recheck](continuation-acceptance/continuation-audit.json) · [Freeze](continuation-acceptance/freeze.json)

## Comparison with frozen issue #44

The original #44 cohort contained Target, Netflix, Ford, NVIDIA,
McDonald's, and Disney. The second fresh cohort contained Mastercard,
Oracle, PepsiCo, Adobe, eBay, and Salesforce. The #44 columns retain the
original score. The #45 columns use the corrected scorer pinned for #54.
[Original #44 decision](SEC_ACCEPTANCE.md) · [#54 source manifest](continuation-acceptance/manifest.json)

| Measure | #44 cold | #44 warm | #45 cold | #45 warm |
| --- | ---: | ---: | ---: | ---: |
| Correct numeric answers | 0/12 | 0/12 | 0/12 | 0/12 |
| Supported numeric answers | 0/12 | 0/12 | 0/12 | 0/12 |
| Grounded abstentions | 0/3 | 0/3 | 0/3 | 0/3 |
| Supported opened citation responses | 0/1 | 0/1 | 0/0 | 0/0 |
| Exact result and citation-set replay | 15/15 | 15/15 | 15/15 | 15/15 |
| Planner requests | 0 | 0 | 0 | 0 |
| Question latency in ms, median (min–max) | 28.45 (7.00–48.42) | 9.85 (6.50–20.74) | 19.47 (11.73–47.25) | 11.53 (9.87–17.94) |

Each cohort matched 3/21 reviewed observations at extraction and 0/21 at
reusable verification. Eighteen observations in each cohort had independent
inline corroboration. The three #45 matches were Salesforce FY2022–FY2024.
They remained provisional because applicable disclosures could not be
established. Both Adobe originals yielded provisional amounts with missing
period starts, so their observations did not match the reviewed periods.
The earlier #44 matches were Netflix FY2022–FY2024.
[Original #44 observation audit](fresh-score.json) ·
[#45 observation audit](continuation-acceptance/score.json)

Peak Windows working sets for the runner and planner were 57.19 and 513.33
MiB for #44, and 56.06 and 513.00 MiB for #45. Peak sampled device VRAM was
0 MiB in both runs. The #45 run took 80 VRAM samples on an NVIDIA GeForce
RTX 5060 Laptop GPU. The planner used CPU inference with zero GPU layers.
Question latency includes opening cited evidence when present. Intake and
planner startup are timed separately. Both runs stopped before a planner
request, so these timings cover the evidence-gap paths.
[Live run and memory samples](continuation-acceptance/live.json.gz)

## First evidenced stop per case

Cold and warm classifications and findings matched. Thirteen cases first
stopped at extraction and two at verification. All requests reached evidence
handling. The cases marked with an asterisk received a blocking
`unsupported_abstention_claim` finding in each pass. The score also records
missing required evidence separately.
[Per-case findings](continuation-acceptance/score.json) ·
[Intake diagnostics and result payloads](continuation-acceptance/live.json.gz)

| Case | Issuer and request | First evidenced stop | Cold / warm ms |
| --- | --- | --- | ---: |
| P6F-01 | Mastercard FY2024 lookup | Extraction. Intake recorded an unsupported layout and fell back to the Microsoft cover check. | 33.71 / 9.87 |
| P6F-02 | Mastercard FY2023–FY2024 growth | Extraction. The fallback established neither requested observation. | 11.84 / 10.20 |
| P6F-03 | Oracle FY2024 lookup | Extraction. Intake recorded an unsupported layout and fell back to the Microsoft cover check. | 44.88 / 13.41 |
| P6F-04 | Oracle FY2023–FY2024 growth | Extraction. The fallback established neither requested observation. | 13.94 / 11.53 |
| P6F-05 | PepsiCo FY2024 lookup | Extraction. Intake recorded an unsupported layout and fell back to the Microsoft cover check. | 47.25 / 13.20 |
| P6F-06 | PepsiCo FY2023–FY2024 growth | Extraction. The fallback established neither requested observation. | 14.26 / 13.20 |
| P6F-07* | Adobe FY2024 lookup | Extraction. The emitted provisional observation lacked a period start. Intake recorded an inline concept conflict and unresolved disclosures. | 36.04 / 13.70 |
| P6F-08* | Adobe FY2023–FY2024 growth | Extraction. Both provisional observations lacked period starts. | 11.75 / 10.81 |
| P6F-09 | eBay FY2024 lookup | Extraction. The parser could not establish one total revenue row. | 38.28 / 11.13 |
| P6F-10 | eBay FY2023–FY2024 growth | Extraction. The parser could not establish either observation from the statement. | 14.28 / 14.02 |
| P6F-11* | Salesforce FY2024 lookup | Verification. The observation matched extraction and remained provisional pending applicable disclosures. | 36.52 / 10.39 |
| P6F-12* | Salesforce FY2023–FY2024 growth | Verification. Both observations matched extraction and remained provisional pending applicable disclosures. | 11.73 / 10.57 |
| P6F-13* | eBay FY2021 absence with FY2024 companion | Extraction. The parser could not establish the total revenue row, a cited period inventory, or a verified FY2024 companion. | 13.82 / 10.81 |
| P6F-14* | Adobe FY2017 displayed but unverifiable | Extraction. The provisional observation lacked a period start. Intake also recorded missing inline corroboration. | 35.59 / 17.94 |
| P6F-15 | PepsiCo FY2022–FY2023 equal-length growth | Extraction. The fallback established neither observation before the fiscal calendar comparison. | 19.47 / 13.50 |

## Reproduce on Windows

Run from the repository root with the
[pinned Python environment](README.md#reproduce-on-windows) and the two
separately held [#54 archives](CONTINUATION_HOLDOUT.md). The launcher
exports runner, scorer, and production code from the pinned revisions and
checks the snapshot against the freeze before copying the runner archive.
Set `$custody` to the local custody directory. Verify the retained artifact bytes, recreate the
frozen workspace, and replay all 30 results and citation sets offline.

```powershell
$production = 'f400e2eb7d7223ea07a001626c237ec958ac3bc5'
$evaluation = '6f4f06c8741919a06ffcfbb45a1473c3928cb388'
$phase = 'artifacts/phase06'
$records = "$phase/continuation-acceptance"
$custody = '../FRAG-SEC-Holdout-54'
$run = "build/phase06-fresh-45-replay-$([guid]::NewGuid())"
Get-Content "$records/SHA256SUMS" | ForEach-Object {
    $hash, $name = $_ -split '  ', 2
    if ((Get-FileHash -LiteralPath "$records/$name").Hash -ne $hash) {
        throw "Retained artifact hash differs for $name."
    }
}
& "$phase/acceptance.ps1" -Mode Freeze -Destination $run -Custody $custody `
    -FreshContinuation -ContinuationRevision $production -EvaluationRevision $evaluation `
    -SavedFreeze "$records/freeze.json"
& "$phase/acceptance.ps1" -Mode Replay -Destination $run -Custody $custody `
    -SavedLive "$records/live.json.gz"
if ($LASTEXITCODE -ne 0) { throw 'Expected 30/30 exact replays.' }
& "$phase/acceptance.ps1" -Mode Score -Destination $run -Custody $custody
if ($LASTEXITCODE -ne 2) { throw 'Expected the measured gate failure.' }
```

Regenerated replay includes fresh intake timings. Use both retained reports
to reproduce the published score byte for byte. The scorer exits 2 for the
measured gate failure.

```powershell
$expected = (Resolve-Path "$custody/scorer/expected.zip").Path
.venv/Scripts/python.exe "$run/scoring/$phase/fresh_score_v2.py" `
    "$run/runner/freeze.json" "$run/runner/inputs.zip" $expected `
    "$records/live.json.gz" "$records/replay.json.gz" "$run/scoring/retained-score.json"
if ($LASTEXITCODE -ne 2) { throw 'Expected the measured gate failure.' }
if ((Get-FileHash "$run/scoring/retained-score.json").Hash -ne (Get-FileHash "$records/score.json").Hash) {
    throw 'Retained score differs.'
}
```

A fresh timing run also requires the
[pinned model and Windows GPU sampler](SEC_ACCEPTANCE.md#reproduce-on-windows).
Use a new destination and the same revisions. The new freeze and reports
will record current timings.

```powershell
$run = "build/phase06-fresh-45-live-$([guid]::NewGuid())"
& "$phase/acceptance.ps1" -Mode Freeze -Destination $run -Custody $custody `
    -FreshContinuation -ContinuationRevision $production -EvaluationRevision $evaluation
& "$phase/acceptance.ps1" -Mode Live -Destination $run -Custody $custody
& "$phase/acceptance.ps1" -Mode Replay -Destination $run -Custody $custody
$replayExit = $LASTEXITCODE
& "$phase/acceptance.ps1" -Mode Score -Destination $run -Custody $custody
if ($LASTEXITCODE -ne 2) { throw 'Expected the measured gate failure.' }
if ($replayExit -ne 0) { throw 'Expected 30/30 exact replays.' }
```

If a replay result or citation differs, the score records the mismatch.
If reingested source evidence differs, the scorer rejects the report pair
and the replay record identifies the affected sources.
