# Phase 6 fresh SEC acceptance

**Decision for issue #44: failed in both passes.** Each pass produced zero of
12 supported numeric answers and zero of three grounded abstentions. All 30
results and citation sets reproduced with sockets blocked. The production
revision and scoring policy were frozen at 2026-11-26 04:45:52 UTC before
the runner archive was copied into the isolated workspace. The custody
verifier confirmed both seals, seven original filings, four layouts, and 15
cases. The independent reference archive stayed outside the runner workspace.
[Freeze](fresh-freeze.json) · [Protocol](FRESH_PROTOCOL.md) · [Custody](SEC_HOLDOUT.md)

| Measure | Phase 5 cold | Phase 5 warm | Phase 6 cold | Phase 6 warm |
| --- | ---: | ---: | ---: | ---: |
| Correct numeric answers | 0/12 | 0/12 | 0/12 | 0/12 |
| Supported numeric answers | 0/12 | 0/12 | 0/12 | 0/12 |
| Supported citations on emitted numeric answers | 0/0 | 0/0 | 0/0 | 0/0 |
| Grounded abstentions | 1/3 | 1/3 | 0/3 | 0/3 |
| Completed cases | 1/15 | 1/15 | 0/15 | 0/15 |
| Exact result and citation-set replay | 15/15 | 15/15 | 15/15 | 15/15 |
| Planner requests | 0 | 0 | 0 | 0 |
| Question latency in ms, median (min–max) | 17.17 (11.89–64.71) | 14.73 (10.44–18.87) | 28.45 (7.00–48.42) | 9.85 (6.50–20.74) |

Phase 5 extracted and verified 0/19 independently reviewed observations.
Phase 6 extracted 3/21, all from Netflix, and independently matched zero
reusable verifications across 21 observations. Eighteen of those observations
had independently corroborated inline XBRL. The other three were from Nvidia
FY2018, which lacks inline XBRL in the original. The three extracted Netflix
facts remained provisional because the workflow could not verify the
applicable disclosures. The cohorts have disjoint issuer families, so the
counts compare generalization checkpoints across different inputs.
[Phase 5 checkpoint](../phase05/SEC_ACCEPTANCE.md#fresh-holdout) · [Phase 6 observation audit](fresh-score.json)

Windows peak working sets for the runner and planner were 61.29 MiB and
513.11 MiB in Phase 5 and 57.19 MiB and 513.33 MiB in Phase 6. Peak sampled
device VRAM was 0 MiB for both checkpoints. Question latency includes opening
citations. Intake and planner startup are recorded separately. The local
pytest suite overlapped the Phase 6 live measurement. Treat the measured
latencies as timings of the observed early stops under that workload.

## First evidenced stop per case

The stop and result classifications were identical in the cold and warm
passes. Each elapsed time includes any citation requests.

| Case | Issuer and question | First stop and evidence | Cold / warm ms |
| --- | --- | --- | ---: |
| P6-01 | Target FY2023 lookup | Extraction. The selected parser found no supported annual header above the revenue row. | 29.07 / 10.28 |
| P6-02 | Target FY2022–FY2023 growth | Request resolution. The CLI returned clarification for the sealed growth wording. | 7.00 / 6.50 |
| P6-03 | Netflix FY2024 lookup | Verification. The extracted observation remained provisional pending applicable disclosures. | 32.42 / 9.66 |
| P6-04 | Netflix FY2023–FY2024 growth | Request resolution. The CLI returned clarification for the sealed growth wording. | 7.69 / 6.86 |
| P6-05 | Ford FY2024 lookup | Extraction. Intake fell back to the Microsoft-specific parser and stopped at its cover check. | 48.42 / 13.13 |
| P6-06 | Ford FY2023–FY2024 growth | Request resolution. The CLI returned clarification for the sealed growth wording. | 12.61 / 11.31 |
| P6-07 | Nvidia FY2025 lookup | Extraction. Intake fell back to the Microsoft-specific parser and stopped at its cover check. | 29.04 / 9.55 |
| P6-08 | Nvidia FY2024–FY2025 growth | Request resolution. The CLI returned clarification for the sealed growth wording. | 7.75 / 6.75 |
| P6-09 | McDonald's FY2024 lookup | Extraction. Intake fell back to the Microsoft-specific parser and stopped at its cover check. | 44.72 / 13.26 |
| P6-10 | McDonald's FY2023–FY2024 growth | Request resolution. The CLI returned clarification for the sealed growth wording. | 14.07 / 7.26 |
| P6-11 | Disney FY2024 lookup | Extraction. Intake fell back to the Microsoft-specific parser and stopped at its cover check. | 41.74 / 12.56 |
| P6-12 | Disney FY2023–FY2024 growth | Request resolution. The CLI returned clarification for the sealed growth wording. | 10.25 / 9.85 |
| P6-13 | Netflix FY2021 absence, with FY2024 companion | Verification. The CLI gave the correct FY2021 absence with a citation and reported a verification gap for the required FY2024 companion. | 34.10 / 20.74 |
| P6-14 | Nvidia FY2018 displayed but unverifiable | Extraction. The workflow fell back to the Microsoft-specific parser and did not establish the independently reviewed displayed FY2018 observation. | 28.45 / 9.97 |
| P6-15 | Target FY2022–FY2023 equal-length comparison | Request resolution. The CLI returned clarification before checking the fiscal calendar. | 7.79 / 7.27 |

The sole citation per pass was P6-13's period inventory. It reopened
successfully and showed FY2022, FY2023, and FY2024. Its statement-heading
locator starts at byte 732540, before the reviewed title-and-units span
starts at 732703. The frozen scorer rejected that locator and assigned
`unsupported_partial` for the missing required companion and
`contradicted_abstention` for the difference from the independently reviewed
abstention plus companion. It also applied `contradicted_abstention` to
P6-14 because the workflow stopped at an earlier evidence gap instead of
establishing the displayed observation. These labels describe the frozen
checks. P6-13 still lacks a verified companion if the heading-span mismatch
is set aside. P6-14 returned no number. The six numeric growth cases and the
equal-length case stopped at request resolution, so this run supplies no
fresh evidence of calculator or planner performance on those questions.
[Input manifest](fresh-inputs.json) · [Per-case score](fresh-score.json)

## Reproduce on Windows

Run from the repository root with the pinned Python environment described
in the [baseline setup](README.md#reproduce-on-windows) and both separately
held archives from the [custody record](SEC_HOLDOUT.md). Supply `-Custody` to
the replay and score commands if the custody directory is elsewhere. The
retained live and replay JSON preserve intake diagnostics, all results, and
opened citation responses. The score binds the uncompressed report digests
and the original manifest, runner archive, and scorer archive hashes.
The published score includes case dispositions and observation matches. Its
`full_score_sha256` binds the full output that contains reviewed reference
details and is reproduced in scorer custody.
[Live record](fresh-live.json.gz) · [Replay record](fresh-replay.json.gz)

```powershell
$run = "build/phase06-retained-$([guid]::NewGuid())"
& artifacts/phase06/acceptance.ps1 -Mode Freeze -Destination $run -SavedFreeze artifacts/phase06/fresh-freeze.json
& artifacts/phase06/acceptance.ps1 -Mode Replay -Destination $run -SavedLive artifacts/phase06/fresh-live.json.gz
& artifacts/phase06/acceptance.ps1 -Mode Score -Destination $run
```

Expect 30/30 exact matches and a failed acceptance decision. The new replay
record has fresh intake timings and therefore its own hash. To reproduce the
retained score byte for byte, score both retained reports. The scorer exits
with code 2 for the measured gate failure.

```powershell
$expected = (Resolve-Path ../FRAG-SEC-Holdout-43/scorer/expected.zip).Path
.venv/Scripts/python.exe "$run/scoring/artifacts/phase06/fresh_score.py" "$run/runner/freeze.json" "$run/runner/inputs.zip" $expected artifacts/phase06/fresh-live.json.gz artifacts/phase06/fresh-replay.json.gz "$run/scoring/retained-score.json"
if ($LASTEXITCODE -ne 2) { throw 'Expected the measured gate failure.' }
$published = Get-Content -Raw artifacts/phase06/fresh-score.json | ConvertFrom-Json
if ((Get-FileHash "$run/scoring/retained-score.json").Hash -ne $published.full_score_sha256) {
    throw 'Retained score differs.'
}
```

A fresh timing run additionally requires the pinned local model and runtime
from the baseline setup and NVIDIA's Windows sampler.

```powershell
$run = "build/phase06-live-$([guid]::NewGuid())"
& artifacts/phase06/acceptance.ps1 -Mode Freeze -Destination $run
& artifacts/phase06/acceptance.ps1 -Mode Live -Destination $run
& artifacts/phase06/acceptance.ps1 -Mode Replay -Destination $run
& artifacts/phase06/acceptance.ps1 -Mode Score -Destination $run
```
