# Phase 3 bounded fiscal-year recovery

Issue #15 extends the collection question workflow with bounded recovery.
One pass remains the default. Bounded mode searches the eligible ranked
candidates for one missing requested year and runs the deterministic
calculator when verified evidence from one filing supports the comparison.

| Validation case | Observed result | Completed actions |
| --- | --- | --- |
| [One pass, one initial fact](bounded-recovery/one-pass.json) | FY2023 revenue of USD 211,915 million. FY2022 missing from selected evidence. | 0 |
| [Bounded, same question and limits](bounded-recovery/recovered.json) | Recovered FY2022. Growth of 6.88% and an increase of USD 13,645 million. | 2 |
| FY2021 unavailable | Kept FY2023 with its citation and named FY2021 as missing. Stopped on no progress. | 1 |
| One-call budget | Recovered both observations. Stopped before calculation. | 1 |
| Zero-second budget | Kept FY2023. Stopped before follow-up search. | 0 |

The paired runs use the same verified Microsoft FY2023 10-K, the same
pinned corpus, and a one-fact first-pass window. Both final contexts can
hold 16 records. The recovered calculation cites the FY2022 and FY2023
cells at original HTML lines 4403 and 4399, with applicable notes and
comparison evidence. The CLI regression test also checks a controlled
separate-source observation and a search that finishes after its deadline.

The default budget allows four search or calculation calls within one
second of question processing on the pinned index. The initial catalogue
read occurs before this budget. Local actions complete synchronously.
Results that cross the time limit stay in the trace and are excluded
from the selected evidence. Recovery of missing notes is a separate slice.

## Windows PowerShell replay

Run from the repository root with the locked dependencies installed. The
harness blocks external network access and freshly validates and replays
each saved record without a loaded model.

```powershell
$recoveryRun = Join-Path 'build' ([guid]::NewGuid().ToString())
.venv/Scripts/python.exe artifacts/phase03/collection-replay.py --growth --bounded --work-dir $recoveryRun
$recoveryStore = Join-Path $recoveryRun 'store'
.venv/Scripts/frag.exe replay-collection (Join-Path $recoveryRun 'recovery-recovered.json') --store $recoveryStore
.venv/Scripts/frag.exe replay-collection artifacts/phase03/bounded-recovery/one-pass.json --store $recoveryStore
.venv/Scripts/frag.exe replay-collection artifacts/phase03/bounded-recovery/recovered.json --store $recoveryStore
.venv/Scripts/python.exe -m pytest -q tests/test_collection_recovery.py
```

Each bounded JSON record contains the resolved request in the outcome,
snapshot and search versions, ranked candidates, initial fact IDs, final
evidence context, budget, typed action arguments and results, elapsed time
checkpoints, and stop reason. Ordinary questions are ephemeral.

The Chrome smoke run submitted the growth question in bounded mode,
displayed 6.88%, and opened the original Note 8 excerpt offline.

```powershell
npm.cmd --prefix web run build
uv run --locked --offline --with playwright python artifacts/phase03/collection-replay.py --bounded --browser --work-dir (Join-Path 'build' ([guid]::NewGuid().ToString()))
```
