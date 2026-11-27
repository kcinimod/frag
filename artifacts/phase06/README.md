# Phase 6 development baseline

[Issue #42 development gate results and replay commands](DEVELOPMENT_GATE.md)

[Issue #44 fresh acceptance decision and replay commands](SEC_ACCEPTANCE.md)

[Issue #51 scoring revision and retained report results](SCORING_REVISION.md)

[Issue #52 exact offline replay and acceptance controls](EXACT_REPLAY.md)

Issue #36 ran 30 fixed questions against 14 preserved SEC originals. In
each cold and warm pass, the opened cohort completed 1 of 15 cases and the
earlier development cohort completed 13 of 15. All 60 results and citation
sets reproduced with sockets blocked. The Phase 5 acceptance result and
records retain their original disposition and bytes.
[Issue #36](https://github.com/kcinimod/frag/issues/36) ·
[Phase 5 acceptance checkpoint](../phase05/SEC_ACCEPTANCE.md)

## Frozen inputs and settings

The pre-change production revision is
`96fa9501f9f383d9586c165cfcda78e3323b4401`. The PowerShell runner uses
`git archive` to export it. The production source, model scripts,
dependency specification, and lockfile are byte-identical to the Phase 5
holdout production revision `67dce6d2232045542c91e42b3239bc6a868534d8`.
The opened run therefore uses the original Phase 5 freeze and scorer. The
earlier freeze pins the same runtime, planner, and retrieval settings and
binds the earlier manifest and reviewed evidence. Compare against these
settings through the first Phase 6 development comparison.
[Opened freeze](../phase05/holdout-freeze.json) · [Earlier freeze](earlier-freeze.json)

The planner is Qwen2.5-0.5B-Instruct Q4_K_M on llama.cpp b6500-a7a98e0f.
The frozen runtime uses a 4,096-token context, four CPU threads, zero GPU
layers, and one slot. Generation uses seed 42, temperature 0, and disabled
prompt caching, with 120 tokens for lookup and 320 for growth. The filing
workflow selects eligible verified annual revenue facts from the selected
filing. Both freezes record the weights, executable and DLL digests,
retrieval configuration, generation settings and dependency versions.

The custody verifier audited the opened archive and reference digests,
seven original SHA-256 hashes and byte lengths, all 15 questions, and
all 19 independently reviewed observations. Those include GE FY2018,
which contributes an extraction reference and lacks inline verification
evidence. For the earlier cohort, intake checked seven compressed and
uncompressed original hashes and sizes, and the scorer checked all 15
question joins and the original evidence spans. The inventory links
the 12 development issuer families with statement title, header, and unit
placement used for the fresh holdout audit.
[Opened custody](../phase05/SEC_HOLDOUT.md) ·
[Earlier questions and originals](../phase05/inputs.json) ·
[Earlier reviewed evidence](../phase05/expected.json) ·
[Issuer and layout inventory](DEVELOPMENT_LAYOUTS.md)

## Results

The counts below apply to each pass. The observation audit counts each
accession and fiscal year once. The case score may count the same
observation again when several questions ask for it. The earlier cases
requested 22 observations, with 22 extraction matches and 21 verified.
[Unique observation audit](observations.json) ·
[Opened score](opened-score.json) ·
[Earlier strict score](earlier-score.json) ·
[Earlier stages](earlier-stages.json)

| Measure | Opened cohort | Earlier development |
| --- | ---: | ---: |
| Unique extraction matches | 0/19 | 20/21 |
| Unique verified facts | 0/19 | 17/21 |
| Correct numeric answers | 0/12 | 12/13 |
| Supported numeric answers | 0/12 | 11/13 |
| Grounded abstentions | 1/3 | 2/2 |
| Completed cases | 1/15 | 13/15 |
| Result and citation matches in offline replay | 15/15 | 15/15 |
| Planner calls | 0 | 12 |

The earlier unique audit includes Microsoft FY2021, which appears in the
reviewed statement but was outside the two-year control extraction.
Apple FY2024's original contributes three extraction matches at provisional
status. The earlier question about that original asks only for FY2024.

| Cohort | Cold median ms (min–max) | Warm median ms (min–max) | Peak runner / planner RAM (MiB) | Peak sampled VRAM (MiB) |
| --- | ---: | ---: | ---: | ---: |
| Opened | 20.1 (13.6–62.7) | 13.9 (12.0–19.6) | 61.59 / 513.16 | 0 |
| Earlier development | 1,804.2 (29.8–7,167.3) | 1,782.7 (11.7–8,053.1) | 88.97 / 578.67 | 0 |

Cold means the first question after a fresh planner process reports
healthy. Warm repeats that question immediately with the same process and
store. Question latency includes opening the cited excerpts and excludes
ingestion and startup. Working-set peaks are per process and VRAM is a
sampled device-wide peak.
[Opened live and replay](opened-live.json.gz) · [Opened replay record](opened-replay.json.gz) ·
[Earlier live record](earlier-live.json.gz) · [Earlier replay record](earlier-replay.json.gz)

### First evidenced failure or completion by case

Cold and warm stopped at the same stages. The opened score retains the
Phase 5 treatment of truthful Cisco diagnostics and partial evidence.
For the original scoring interpretation, see the Phase 5 checkpoint.
[Historical scoring findings](../phase05/SEC_ACCEPTANCE.md#fresh-holdout)

| Opened cases | Earliest evidenced outcome |
| --- | --- |
| P5-01, P5-02, P5-03 | Extraction. The Home Depot statement layout was unsupported. |
| P5-04, P5-05 | Extraction. GE FY2024 fell back to the Microsoft-specific cover check. |
| P5-06 | Completed as a grounded evidence gap. GE FY2018 lacked required inline evidence. The historical observation also went unextracted. |
| P5-07, P5-08, P5-09 | Extraction. Coca-Cola's total revenue row went unrecognized. P5-09 also lacked the required period inventory citation. |
| P5-10, P5-11 | Extraction. The UPS statement layout was unsupported. |
| P5-12, P5-13 | Extraction. Cisco's dated header failed the full-date check. |
| P5-14, P5-15 | Extraction. The Procter & Gamble statement layout was unsupported. |

| Earlier cases | Earliest evidenced outcome |
| --- | --- |
| msft-growth | Presentation. Correct growth with opened excerpts that lack the USD measure. |
| aapl-2024-present | Verification. The original amount was extracted but remains provisional pending applicable disclosure verification. |
| msft-lookup, aapl-lookup, aapl-growth, amzn-lookup, amzn-growth, wmt-lookup, wmt-growth, goog-lookup, goog-growth, intc-lookup, intc-growth | Complete with supported numeric answers. |
| aapl-absent, intc-incompatible | Complete with grounded abstentions and cited companion evidence. |

## Phase 6 scoring controls

The Phase 6 `score_case` entry point adds two fields to the per-case score.
`incomplete` identifies a truthful gap on an answerable case that has no
blocking findings. `supported_partial` marks a verified, cited companion on
an answerable growth case with a withheld calculation. The Cisco diagnostics are
incomplete in both passes. A synthetic growth control retains Apple FY2023
revenue and its original citations while withholding the percentage because
the FY2022 observation was unavailable. Neither control earns supported-answer
or grounded-abstention credit. Wrong amounts, unsupported citations and
operands, contradicted reasons, and replay mismatches remain blocking.
[Phase 6 scorer](revenue_score.py) · [Controls](../../tests/test_phase06_acceptance.py)

Run the scorer controls from the repository root.

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_phase06_acceptance.py
```

## Reproduce on Windows

From the repository root, set up the locked environment with the exact
Python version required by both freezes.

```powershell
uv sync --locked --python 3.12.14
if ($LASTEXITCODE -ne 0) { throw 'Pinned Python environment setup failed.' }
```

Use the local Phase 5 custody archives. The default custody path is
`../FRAG-SEC-Holdout-32`. Pass `-Custody` to use another local copy.
Replay uses saved plans, reingests the original bytes, and reopens any
original citation routes with all socket connections blocked. Review the
two 30/30 replay lines and the score, stage, and observation files under
the destination.

```powershell
$replay = "build/phase06-replay-$([guid]::NewGuid())"
& artifacts/phase06/baseline.ps1 -Destination $replay -ReplayRetained
```

Fresh measurement requires the frozen model at `.frag-model/model.gguf`,
its Windows runtime at `.frag-model/runtime`, `nvidia-smi`, and free local
port 18089. The runner checks model and runtime hashes before either
cohort runs. The same command replays and scores the new cold and warm
results after measurement. Fresh timings and report digests will differ.

```powershell
$live = "build/phase06-live-$([guid]::NewGuid())"
& artifacts/phase06/baseline.ps1 -Destination $live
```

For retained replay, this check compares both regenerated reports and the
unique observation audit with the checked-in records. Replay ingest timings
are measured again, so the scorer hashes of those replay files also change.

```powershell
@'
import gzip
import json
from pathlib import Path
import sys

actual = Path(sys.argv[1])
retained = Path("artifacts/phase06")
for name in ("opened", "earlier"):
    repeated = json.loads((actual / f"{name}-replay/report.json").read_bytes())
    saved = json.loads(gzip.decompress((retained / f"{name}-replay.json.gz").read_bytes()))
    for report in (repeated, saved):
        for source in report["sources"].values():
            del source["ingest_ms"]
    assert repeated == saved, name
for name in ("opened-score", "earlier-score", "earlier-stages", "observations"):
    repeated = json.loads((actual / f"{name}.json").read_bytes())
    saved = json.loads((retained / f"{name}.json").read_bytes())
    if name != "observations":
        for report in (repeated, saved):
            del report["replay_sha256"]
    assert repeated == saved, name
print("Retained results, citation sets, scores, and observations reproduced.")
'@ | .venv/Scripts/python.exe - $replay
if ($LASTEXITCODE -ne 0) { throw 'Retained baseline comparison failed.' }
```
