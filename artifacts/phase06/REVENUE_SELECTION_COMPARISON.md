# Rules-shortlisted SEC revenue selection

Rules alone and the rules-shortlisted model each selected the independently
reviewed consolidated revenue row in all seven opened #54 filings and matched
**12 of 21** annual observations exactly. The model-only strategy selected the
reviewed row in two filings and matched **0 of 21** observations. Neither model
strategy improved exact extraction over rules alone on this development cohort.
[Issue #58](https://github.com/kcinimod/frag/issues/58) ·
[Paired score](revenue-selection-comparison/score.json) ·
[Paired run record](revenue-selection-comparison/run.json.gz)

| Filing | Reviewed row | Rules alone | Model only | Shortlisted model |
| --- | --- | --- | --- | --- |
| Mastercard FY2024 | `table-56/row-6` | 3 exact | Wrong row, scope rejected | 3 exact |
| Oracle FY2024 | `table-36/row-9` | 3 exact | Wrong row, scope rejected | 3 exact |
| PepsiCo FY2024 | `table-28/row-3` | Reviewed row, extraction gap | Reviewed row, extraction gap | Reviewed row, extraction gap |
| Adobe FY2017 | `table-121/row-9` | Reviewed row, extraction gap | Wrong row, scope rejected | Reviewed row, extraction gap |
| Adobe FY2024 | `table-32/row-8` | Reviewed row, extraction gap | Reviewed row, extraction gap | Reviewed row, extraction gap |
| eBay FY2024 | `table-31/row-5` | 3 exact | Wrong row, scope rejected | 3 exact |
| Salesforce FY2024 | `table-31/row-7` | 3 exact | Wrong row, scope rejected | 3 exact |

One row per filing survived the rules shortlist and reached the model. The
model selected each one. The nine missed observations therefore came from the
shared extractor. PepsiCo lacked a supported shared fiscal year-end, and both
Adobe filings had unresolved fiscal period starts. All retained observations
were provisional. No strategy emitted verified observations.

Rules alone and the shortlisted model abstained on the absent-target control.
The shortlisted model made no call because no rows survived. The model-only
strategy chose the units row and the extractor rejected it. On the distractor
control, all three strategies selected the consolidated total and extracted
USD 15 million for FY2023 and USD 19 million for FY2024 from the expected cells.
The shortlist included both the total and the net sales subtotal.

Both model strategies used the same Qwen2.5 1.5B Instruct Q4_K_M weights,
prompt, representation, grammar, batch limits, and selection policy. The
run records shortlist membership, submitted batches, nominations, selections,
original-cell evidence, and validation stops. The independent score records the
first observed failure and lists the affected fiscal years. If the reviewed row
reached the model but the shortlist removed other rows from its table, the
score preserves that context gap as a possible cause of a wrong selection.

| Strategy | Model calls across nine cases | Selection and validation across seven filings |
| --- | ---: | ---: |
| Rules alone | 0 | 0.105 s |
| Model only | 160 | 73.570 s |
| Shortlisted model | 8 | 2.074 s |

The measured Windows run shared a llama.cpp b6500 Vulkan server on an
NVIDIA RTX 5060 Laptop GPU. The cumulative Python and server peak working
sets were 73 MiB and 2,000 MiB. Device-wide memory samples were 1,517–1,518 MiB.
Peak VRAM and per-strategy server peak RAM were unmeasured. Timings exclude
shared parsing and server startup. The cohort is open for development and
the measurements do not determine the later issuer-disjoint comparison.

## Reproduce on Windows

Use the locked Python environment, the local opened #54 archives, and the
model and Vulkan runtime described in the model-only setup. Run from the
repository root. The runner uses the archive of originals and the independent
scorer uses both archives. Scoring replays recorded model responses and checks
all three strategies with socket operations blocked.
[Model and runtime setup](REVENUE_SELECTION_MODEL.md#reproduce-on-windows) ·
[Opened archive custody](CONTINUATION_HOLDOUT.md)

```powershell
$custody = '../FRAG-SEC-Holdout-54'
$run = "build/revenue-selection-58-$([guid]::NewGuid())"
$runtime = 'build/llama-b6500-vulkan/llama-server.exe'
.venv/Scripts/python.exe artifacts/phase06/revenue_selection_model.py "$custody/runner/inputs.zip" $run --compare --runtime $runtime --gpu-layers 99 --device Vulkan1 --port 18158
if ($LASTEXITCODE -ne 0) { throw 'Paired selection run failed.' }
.venv/Scripts/python.exe artifacts/phase06/revenue_selection_model_score.py "$custody/runner/inputs.zip" "$custody/scorer/expected.zip" "$run/run.json.gz" "$run/score.json"
if ($LASTEXITCODE -ne 0) { throw 'Paired replay and scoring failed.' }
Get-Content "$run/score.json"
```

Replay the retained run without model weights or a running server.

```powershell
$custody = '../FRAG-SEC-Holdout-54'
$saved = 'artifacts/phase06/revenue-selection-comparison'
$score = "build/revenue-selection-58-score-$([guid]::NewGuid()).json"
.venv/Scripts/python.exe artifacts/phase06/revenue_selection_model_score.py "$custody/runner/inputs.zip" "$custody/scorer/expected.zip" "$saved/run.json.gz" $score
if ($LASTEXITCODE -ne 0) { throw 'Retained replay failed.' }
$actual = (Get-Content $score -Encoding UTF8) -join [char]10
$expected = (Get-Content "$saved/score.json" -Encoding UTF8) -join [char]10
if ($actual -cne $expected) { throw 'Retained score differs.' }
```
