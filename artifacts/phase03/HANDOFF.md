# Phase 3 collection retrieval handoff

Issue #12 extends partial growth results to include the available statement
and applicable notes for the verified year. With FY2021 unavailable, the
workspace shows Microsoft FY2023 revenue of **USD 211,915 million**, names
FY2021 as the missing requirement, and opens Note 8 from the preserved
original offline. The complete FY2022–FY2023 answer still shows **6.88%**.
Annual lookups link to applicable notes. Bounded retrieval can reuse a
verified same-filing pair when the first pass selects the two years from
separate filings. If it runs out of calls before calculating, it includes
the comparison caveats supported by the context it recovered.
[Issue #12](https://github.com/kcinimod/frag/issues/12)

The Windows rerun covered 11 paired cases and matched all 22 offline
replays. One-pass and bounded retrieval produced 1 and 4 supported answers,
respectively. All 38 one-pass citations and 61 bounded citations opened and
passed the excerpt checks. The table below records the original #16 run.

```powershell
$phase3Run = Join-Path 'build' ('issue12-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe artifacts/phase03/collection-replay.py --growth --bounded --paired --work-dir $phase3Run
npm.cmd --prefix web run build
uv run --locked --offline --with playwright python artifacts/phase03/collection-replay.py --growth --bounded --browser
```

The paired command writes the fresh JSON transcripts and measurements to
`$phase3Run`. The committed #16 transcripts below still replay with their
recorded retrieval versions.

## Original paired run

Bounded retrieval turned three partial results into supported results across
11 paired questions, with no outcome regressions. It recovered the Microsoft
FY2022 observation in one case and the original statement and disclosures in
another. Both recovered answers returned **6.88%** for FY2022 to FY2023.
The third recovery used a labeled synthetic zero-baseline fixture.
[Issue #16](https://github.com/kcinimod/frag/issues/16)

| Measure | One-pass | Bounded |
| --- | ---: | ---: |
| Individual verified fact recall | 18/19 (94.7%) | 19/19 (100%) |
| Complete final-context coverage | 1/11 (9.1%) | 5/11 (45.5%) |
| Supported answers | 1/11 (9.1%) | 4/11 (36.4%) |
| Correct partial answers | 9/11 (81.8%) | 6/11 (54.5%) |
| Correct citations opened offline | 28/28 | 56/56 |
| Abstentions from a complete answer | 10/11 | 7/11 |
| Clarifications included in abstentions | 1 | 1 |
| Bounded action calls | 0 | 15 |
| Median cold process latency | 295.013 ms | 296.553 ms |
| Median warm CLI latency | 15.004 ms | 15.947 ms |
| Peak CLI process working set | 70.7 MiB | 71.1 MiB |

Fact recall counts independently specified verified observations available in
the corpus for each question. Coverage uses the actual final context and
requires both operands, the statement table, the applicable notes and
disclosures, and a compatible comparison. The call-limited run reached
complete coverage and stopped before calculation. Supported answers include
the verified zero-baseline result with absolute change. Partial answers must
preserve supported observations and identify the unresolved requirement.
Citation counts include partial findings. The runner checks amounts and
landmarks in the original excerpts. Bounded action counts include the
calculator when invoked as an action. One-pass directly invokes the same
deterministic calculator.

| Case | One-pass | Bounded | Bounded calls |
| --- | --- | --- | ---: |
| Complete Microsoft pair | 6.88% | 6.88% | 1 |
| FY2022 omitted on first pass | Partial, FY2023 | 6.88% after targeted search | 2 |
| Statement and disclosures omitted on first pass | Partial, both amounts | 6.88% after following table and disclosure pointers | 3 |
| FY2021 absent as a verified fact | Partial, FY2023 | Same partial, no progress | 1 |
| Unopenable disclosure | Partial, both amounts | Same partial, unresolved Note 1 | 2 |
| Incompatible reporting basis | Partial, both amounts | Same partial, unresolved compatibility | 1 |
| Zero baseline with instruction-like disclosure | Partial, both amounts | Undefined percentage, USD 12 million increase | 3 |
| Ambiguous company | Clarification | Clarification | 0 |
| Two-record final context limit | Partial, both amounts | Same partial, no space for context | 0 |
| Two-call limit | Partial, both amounts | Complete context, calculation deferred | 2 |
| Zero-second limit | Partial, both amounts | Same partial, time exhausted | 0 |

The zero-baseline fixture's original disclosure includes text asking for a
different year and action arguments. The citation opens that text. The run
only followed the verified Note 1 reference and calculated with FY2022 and
FY2023. The unopenable-disclosure fixture uses an intentionally out-of-range
locator. It returned no evidence from that source action and preserved both
original cell citations.

## Reproduce on Windows

From the repository root in PowerShell, use new output directories and put
`nvidia-smi` on PATH. The paired runner verifies the preserved inputs, builds the disposable fixture evidence,
executes both CLI modes, and replays every saved outcome with external Python
sockets blocked.

```powershell
.venv/Scripts/python.exe artifacts/phase03/collection-replay.py --growth --bounded --paired --work-dir .venv/issue16-paired5
.venv/Scripts/frag.exe replay-collection artifacts/phase03/paired-validation/paired-recover-context-bounded.json --store .venv/issue16-paired5/store
uv run --locked --offline --with playwright python artifacts/phase03/collection-replay.py --bounded --browser --work-dir .venv/issue16-browser-final
```

The [paired run directory](paired-validation/) contains all 22 first-run
records with the snapshot, versions, ranked candidates, exact selected
context, action checkpoints, calculation traces and stop reasons.
[Per-question measurements](paired-validation/paired-summary.json) record
cold and warm samples. The [base corpus manifest](corpus-manifest.json) pins
the two preserved Microsoft filings and a provisional synthetic distractor.
The [comparison runner](paired_comparison.py) defines the three additional
synthetic controls. Both modes used the same snapshot and the same limits
for each pair. The final context limit was 16 records except in the
two-record case. The collection workflows used deterministic retrieval and
calculation throughout, with no model or prompt loaded.

Measurements were taken on the Lenovo 83VK Windows 11 laptop with an Intel
Core Ultra 7 251HX and NVIDIA GeForce RTX 5060 Laptop GPU. Cold latency
includes a fresh Python process and CLI startup with the Windows file cache
in normal use. Warm latency covers three subsequent CLI calls in each worker
process. Both include index loading and record writing. RAM uses the Windows
process peak working-set counter. NVIDIA device memory sampled every 100 ms
peaked at **0 MiB** across 88 samples for the paired run. That is a
device-wide sample on the NVIDIA adapter. Chrome also opened the FY2022 and
FY2023 cells and the Note 8 excerpt from the local workspace with external
browser requests blocked.

This small suite measures controlled coverage gaps and one independently
verified real filing pair. It gives no estimate of retrieval performance
across unseen filings or questions. The older Phase 3 records remain
replayable through their recorded retrieval versions.
