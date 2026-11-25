# Phase 5 SEC acceptance checkpoint

**Acceptance failed.** Each pass produced 0 of 12 supported numeric answers
and 1 of 3 grounded abstentions. The frozen minimums were 11 and 3 per pass.
All 30 results and citation sets matched in socket-blocked replay. The seven
fresh originals yielded no extracted revenue facts, and no question reached
the planner. [Issue #34](https://github.com/kcinimod/frag/issues/34) ·
[Frozen protocol](HOLDOUT_PROTOCOL.md) · [Per-case score](holdout-score.json)

## Paired development comparison

Each checkpoint ran the same 15 questions against the same seven originals.
The manifests share the question, reference, model weights, runtime DLL and
executable hashes, generation settings, and retrieval configuration. The
five checkpoints change the parser, verifier and filing-scoped behavior in
sequence. The scores show checkpoint deltas across those changes.
Accuracy counts correct numeric results among 13 answerable cases. Citation
support counts supported results among emitted numeric answers. Coverage and
completion use all 15 questions. The 22 requested observations count
observations per case, including repeated periods. Cold and warm pass counts
agree throughout. [Development manifest](inputs.json) ·
[Independent evidence](expected.json)

| Checkpoint | Extracted / verified (of 22) | Numeric accuracy | Citation support | Numeric coverage | Grounded abstentions | Completed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline [#27](score.json) | 8 / 7 | 4/13 | 2/4 | 4/15 | 1/2 | 3/15 |
| Shared-date extraction and lookup verification [#28](unseen-lookup-score.json) | 17 / 16 | 7/13 | 5/7 | 7/15 | 1/2 | 6/15 |
| Dated statements and disclosure verification [#29](development-layout-score.json) | 22 / 21 | 8/13 | 7/8 | 8/15 | 1/2 | 8/15 |
| Compatible growth and period-length check [#30](verified-growth-score.json) | 22 / 21 | 12/13 | 11/12 | 12/15 | 2/2 | 13/15 |
| Grounded statement-period and other evidence gaps [#31](evidence-gap-score.json) | 22 / 21 | 12/13 | 11/12 | 12/15 | 2/2 | 13/15 |

| Checkpoint | Cold median ms (range) | Warm median ms (range) | Runner / planner peak RAM (MiB) | Peak device VRAM (MiB) |
| --- | ---: | ---: | ---: | ---: |
| #27 | 40.2 (9.1–6,309.6) | 54.5 (10.6–8,241.0) | 87.60 / 573.57 | 0 |
| #28 | 394.2 (9.0–6,299.6) | 368.7 (7.9–6,335.1) | 88.80 / 573.68 | 0 |
| #29 | 1,597.7 (12.1–5,958.2) | 1,622.1 (5.1–7,246.1) | 88.82 / 573.70 | 0 |
| #30 | 1,871.7 (24.7–5,678.7) | 1,834.4 (9.2–5,705.2) | 89.10 / 578.81 | 0 |
| #31 | 1,708.5 (27.5–7,212.1) | 1,747.5 (10.5–8,309.0) | 89.16 / 578.66 | 0 |

The paired changes affected these cases in both passes.

- **Baseline.** Extraction blocked eight answerable cases. The Apple FY2024
  amount remained provisional. Request resolution returned clarification
  for Intel's equal-length question. Microsoft lookup and growth lost
  presentation credit for incomplete statement citations.
- **Shared-date extraction and verification.** Amazon, Alphabet and Walmart
  lookups completed. Their growth pairs reached verification and were withheld
  at the growth eligibility check. Both Intel answerable cases still failed
  at extraction.
- **Dated layouts.** Intel lookup completed, and the Microsoft lookup citation
  gained support. Four verified growth pairs still needed comparison support.
- **Growth verification.** Those four growth pairs completed, and the Intel
  equal-length request returned a grounded abstention. The Microsoft growth
  excerpt still lacked the USD measure and the Apple FY2024 case still stopped
  at verification.
- **Evidence-gap reporting.** Apple FY2020 gained a statement-period citation
  confirming absence and retained the verified FY2023 amount. Apple FY2024
  received a more specific verification explanation. The remaining two
  development failures persisted. [Strict development rescore](ACCEPTANCE_SCORER.md)

Planner requests and proposals both increased from 7 to 8, 8, 12 and 12 per
pass. All five checkpoints replayed 30/30 results and citations. The latency
medians include cases that returned without inference, so the increase reflects
the changing proportion of questions reaching the planner. Latency includes
opening citation routes and excludes ingestion and startup. RAM uses separate
process high-water marks, and device VRAM uses Windows NVIDIA samples.

## Fresh holdout

The independent custody verifier reopened all seven 10-Ks, audited 19
statement observations and their original evidence across four layouts,
and confirmed zero issuer overlap. The production snapshot included only
the existing Apple and Microsoft reviewed references. The runner checked
their issuer, accession and hash against each holdout source, and the
intake reports recorded zero matched reviewed references.
[Custody and original archive access](SEC_HOLDOUT.md) ·
[Freeze manifest](holdout-freeze.json)

| Measure | Cold | Warm |
| --- | ---: | ---: |
| Correct numeric answers | 0/12 | 0/12 |
| Supported numeric answers | 0/12 | 0/12 |
| Supported citations among emitted answers | 0/0 | 0/0 |
| Numeric coverage | 0/15 | 0/15 |
| Grounded abstentions | 1/3 | 1/3 |
| End-to-end completions | 1/15 | 1/15 |
| Offline result and citation matches | 15/15 | 15/15 |
| Question latency, median ms (range) | 17.2 (11.9–64.7) | 14.7 (10.4–18.9) |

Peak working sets were 61.29 MiB for the runner and 513.11 MiB for the
planner. Sampled device VRAM peaked at 0 MiB. These holdout latencies cover
early evidence gaps. The model started for each pair of questions, with
zero requests, proposals, trace steps or returned citation links.

| Cases | Earliest outcome and original evidence |
| --- | --- |
| P5-01–03, Procter & Gamble | The generic statement intake fell back to the Microsoft-specific parser. Both requested annual observations went unextracted. The equal-length case also lacked the cited operands and reviewed fiscal-calendar explanation. |
| P5-04–05, GE FY2024 | The fallback parser stopped at the cover check. No lookup or growth operand reached verification. |
| P5-06, GE FY2018 | The historical statement displays the requested year, and the preserved original lacks the required inline verification evidence. The workflow reported an evidence gap and withheld the number. |
| P5-07–09, Coca-Cola | The shared-date parser did not identify a supported total revenue row. The absence case lacked original period-header evidence and the verified current operand. |
| P5-10–11, Home Depot | The fallback parser stopped at the cover check. |
| P5-12–13, Cisco | The dated parser rejected the header layout after looking for one row of full dates. |
| P5-14–15, UPS | The fallback parser stopped at the cover check. |

The frozen scorer assigned four `contradicted_abstention` findings per
pass. In the absence and unequal-period cases the displayed gaps failed to
establish the expected reasons. The Cisco cases used parser wording outside
the frozen scorer's allowlist. Those findings reflect unproven explanations.
The responses made zero explicit claims that a displayed year was absent.
The single `unsupported_citation` code reflects the required statement-period
citation that was missing. The two `unsupported_partial` codes reflect the
required operands that were missing. No numeric result was emitted.

The observed bottleneck is statement and period extraction. This run provides
no evidence for changing retrieval or the planner. Reusable verification
coverage on fresh filings remains unmeasured because intake yielded zero
facts. The development Microsoft growth citation gap also remains open.
This cohort has now been opened for evaluation. Any issuer family used to
guide extractor changes must be replaced before another acceptance run.

## Windows reproduction

Use the repository root, the locked Python environment and the archives in
local custody. For a fresh live run, the local model cache must contain the
frozen Qwen 0.5B weights as `.frag-model/model.gguf` and the matching Windows
runtime as `.frag-model/runtime`. The snapshot exports production
`67dce6d2232045542c91e42b3239bc6a868534d8` and stays separate from working-tree
production code and scorer materials. The first attempted launch stopped
before any question because the Windows null device was blocked. Commit
`8f789df` records the operational correction and replacement freeze.

```powershell
$ErrorActionPreference = 'Stop'
$snapshot = & artifacts/phase05/holdout-snapshot.ps1 -Destination "build/phase05-acceptance-$([guid]::NewGuid())" -WithModel
$custody = (Resolve-Path ../FRAG-SEC-Holdout-32).Path
Copy-Item -LiteralPath artifacts/phase05/holdout-freeze.json -Destination "$snapshot/freeze.json"
Copy-Item -LiteralPath "$custody/runner/inputs.zip" -Destination "$snapshot/inputs.zip"
$runner = "$snapshot/artifacts/phase05/holdout.py"
.venv/Scripts/python.exe $runner live "$snapshot/freeze.json" --model "$snapshot/model" --inputs "$snapshot/inputs.zip" --work "$snapshot/live"
if ($LASTEXITCODE -ne 0) { throw 'Holdout measurement failed.' }
.venv/Scripts/python.exe $runner replay "$snapshot/freeze.json" --inputs "$snapshot/inputs.zip" --work "$snapshot/replay" --saved-run "$snapshot/live/report.json"
if ($LASTEXITCODE -ne 0) { throw 'Holdout replay failed.' }
```

To replay the retained run with the planner stopped, create the snapshot
without `-WithModel`, copy in the frozen manifest and runner archive, and
recreate the exact live JSON from its retained gzip.

```powershell
$ErrorActionPreference = 'Stop'
$snapshot = & artifacts/phase05/holdout-snapshot.ps1 -Destination "build/phase05-replay-$([guid]::NewGuid())"
$custody = (Resolve-Path ../FRAG-SEC-Holdout-32).Path
Copy-Item -LiteralPath artifacts/phase05/holdout-freeze.json -Destination "$snapshot/freeze.json"
Copy-Item -LiteralPath "$custody/runner/inputs.zip" -Destination "$snapshot/inputs.zip"
.venv/Scripts/python.exe -c "import gzip, pathlib, sys; pathlib.Path(sys.argv[2]).write_bytes(gzip.decompress(pathlib.Path(sys.argv[1]).read_bytes()))" artifacts/phase05/holdout-live.json.gz "$snapshot/live.json"
if ($LASTEXITCODE -ne 0) { throw 'Could not unpack the retained run.' }
.venv/Scripts/python.exe "$snapshot/artifacts/phase05/holdout.py" replay "$snapshot/freeze.json" --inputs "$snapshot/inputs.zip" --work "$snapshot/replay" --saved-run "$snapshot/live.json"
if ($LASTEXITCODE -ne 0) { throw 'Holdout replay failed.' }
```

In the scorer environment, point `PYTHONPATH` at the snapshot's production
code. Score directly from the retained reports or substitute the live and
replay reports created above. Exit code 1 with a written score records a
rejected acceptance result.

```powershell
$env:PYTHONPATH = "$snapshot/src"
.venv/Scripts/python.exe artifacts/phase05/holdout_score.py "$snapshot/freeze.json" "$snapshot/inputs.zip" "$custody/scorer/expected.zip" artifacts/phase05/holdout-live.json.gz artifacts/phase05/holdout-replay.json.gz "$snapshot/score.json"
if ($LASTEXITCODE -ne 1 -or -not (Test-Path "$snapshot/score.json")) { throw 'Expected the recorded acceptance rejection.' }
if ((Get-FileHash "$snapshot/score.json").Hash -ne (Get-FileHash artifacts/phase05/holdout-score.json).Hash) { throw 'Retained score did not reproduce.' }
```

The compressed records retain the original SHA-256 values, parser and
evidence versions, intake diagnostics, displayed outcomes, validation records
and model fields. The model fields are null for all 30 questions. Original
filings remain in the hash-pinned runner archive. The scorer bundle holds
the reviewed citations, periods, disclosures and arithmetic independently
of the runner. [Live records](holdout-live.json.gz) ·
[Offline replay](holdout-replay.json.gz) · [Score](holdout-score.json) ·
[Source custody receipt](sec-holdout-receipt.json)
