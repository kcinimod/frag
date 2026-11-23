# FinQA dev evidence comparison

Issue #20 uses the [13-question dev coverage cohort](finqa-dev-cohort.json)
from the annotated-evidence diagnostic. The paired run starts a fresh
planner for each mode and includes one warm result per question in each
mode. The [saved comparison](finqa-dev-comparison.json.gz) retains the cold
probes separately.

## Dev results

| Outcome across 13 warm questions | Annotated | Retrieved |
| --- | ---: | ---: |
| Execution matches | 2 | 2 |
| Symbolic program matches | 2 | 2 |
| Invalid plans | 10 | 8 |
| Executed with a wrong answer | 1 | 3 |

Both modes answered the same two questions correctly and missed the other
11. The pinned scorer reproduced the execution and program counts with
verified parity for both modes. Retrieval omitted four annotated table
rows across `ETR/2011/page_341.pdf-3` and `UNP/2011/page_76.pdf-2`.
Both questions had invalid plans in both modes. The context budget
excluded zero annotated excerpts in this cohort. On
`PM/2017/page_38.pdf-1` and `PNC/2009/page_46.pdf-3`, retrieval had all
annotated evidence and moved from an invalid plan to an executed wrong
answer.

## Windows workload measurements

Measured on the Windows 11 laptop with an Intel Core Ultra 7 251HX
and NVIDIA GeForce RTX 5060 Laptop GPU.

| Measurement | Annotated | Retrieved |
| --- | ---: | ---: |
| Cold server startup plus first question | 3.119 s | 9.083 s |
| Warm cohort wall time, 13 questions | 70.551 s | 116.757 s |
| Warm median question time | 5.361 s | 8.438 s |
| Peak server working set through the cold question | 1,783 MiB | 1,799 MiB |
| Peak server working set through the warm cohort | 1,799 MiB | 1,817 MiB |
| Sampled peak device VRAM, cold and warm | 0 MiB | 0 MiB |

The cold probe starts a fresh server after weight verification and
answers the first cohort question in each mode. The warm pass uses
the same process and runs the full cohort in order, including that first
question. Cold refers to the server process. The warm RAM value is the
process-lifetime Windows working-set high-water mark, read at the end of
the warm cohort. NVIDIA device-wide VRAM was sampled separately during
the cold and warm windows. Scoring and replay ran after measurement.

## Inspect the evidence

Each mode's record includes a `ranking`, `source_excerpts` eligible for
selection, and the actual request in `planner_input.messages`.
`annotated_evidence_omitted.ranking` lists annotated locators that keyword
retrieval did not select. `annotated_evidence_omitted.context` lists
annotated locators selected for consideration whose excerpts missed the
budget or whose required table header missed the budget. Review those
fields alongside the paired failure stages in `summary.cases` and the
executor traces in `modes`. `scores` retains the upstream predictions,
per-ID execution and program matches, and parity discrepancies.

## Frozen protocol for public test

- Use the official splits and pinned upstream revision and hashes in
  `upstream` in the saved comparison. Keep the official membership and
  the disclosure in the [split overlap audit](FINQA_DIAGNOSTIC.md). This
  validation used 13 dev questions and zero demonstrations.
- Use the verified Qwen2.5-1.5B-Instruct Q4_K_M GGUF and llama.cpp
  b6500-a7a98e0f Windows x64 CPU server. The saved `configuration`
  specifies weight and executable hashes, four threads, one slot, 4,096
  context tokens, a 30-second request timeout, and no GPU offload.
- Use the same system prompt, JSON schema and executor in both modes.
  Use temperature zero, seed 42, up to 512 generated tokens, and disabled
  prompt caching. Allow one attempt per question. The full prompt, request
  settings, and implementation digests are in `configuration`.
- Select source excerpts using the annotated locators in one mode. In
  retrieved mode, rank passages and table rows from the supplied report
  by the count of distinct shared case-folded keyword tokens, excluding
  the fixed stopwords in the implementation. Keep positive scores with
  ties in passage order then table order. Attach the original header for
  table rows. Use the same 2,800-byte UTF-8 user-message limit in both
  modes, including the question and JSON formatting. Keep the reference
  answer, program, and annotation values outside the planner input.
- For public test, require one outcome for every official ID in each mode.
  Resume by ID under the same configuration identity and preserve both
  modes' actual requests. Use the pinned upstream evaluator and report
  execution and symbolic program accuracy alongside replay parity,
  full-cohort coverage, and the paired failure stages. Set no numeric
  quality target for this coverage-oriented validation. Public test runs
  follow in the next milestone.

## Run and replay on Windows

Use the pinned input cache, scorer environment, and the pinned runtime
under `.frag-model/runtime`. Prepare the inputs and environment using
the [cache setup](FINQA_DIAGNOSTIC.md#fresh-run-on-windows) and
[scorer dependency setup](FINQA_DIAGNOSTIC.md#offline-scoring-parity).
The runner expects
`qwen2.5-1.5b-instruct-q4_k_m.gguf` under `.frag-model`. If needed,
retrieve the [pinned weights](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/blob/91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_k_m.gguf)
into that location. The runner verifies both the weights and executable
before launching a local server.

From the repository root in PowerShell, run a fresh comparison, then
score it from the saved record. Replay rebuilds both rankings and planner
inputs, executes the saved proposals, and checks any saved upstream
scores without starting the model. A `.json` output path keeps an
uncompressed copy for inspection.

```powershell
$env:TEMP = (Resolve-Path build).Path
$env:TMP = $env:TEMP
$record = Join-Path build ("finqa-dev-comparison-" + [guid]::NewGuid() + ".json.gz")
$scored = Join-Path build ("finqa-dev-scored-" + [guid]::NewGuid() + ".json.gz")
build/finqa-venv/Scripts/python.exe -m frag.finqa_comparison run build/finqa $record --cohort artifacts/phase04/finqa-dev-cohort.json
build/finqa-venv/Scripts/python.exe -m frag.finqa_comparison score build/finqa $record $scored
build/finqa-venv/Scripts/python.exe -m frag.finqa_comparison replay build/finqa artifacts/phase04/finqa-dev-comparison.json.gz
```

The comparison record retains excerpts from the FinQA dataset under its
[MIT license](FINQA_LICENSE.txt).
