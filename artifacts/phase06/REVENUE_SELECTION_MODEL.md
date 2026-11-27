# Model-only SEC revenue selection

The pinned Qwen2.5 1.5B Instruct Q4_K_M model saw all **773 visible
tables and 9,010 rows** in the seven opened #54 filings. It nominated the
independently reviewed row in three filings and retained it after comparison
in two. The extractor matched **0 of 21** reviewed annual observations,
compared with **12 of 21** for rules alone. It emitted zero verified
observations. [Issue #57](https://github.com/kcinimod/frag/issues/57) ·
[Run record](revenue-selection-model/run.json.gz) ·
[Independent score](revenue-selection-model/score.json) ·
[Rules baseline](REVENUE_SELECTION_BASELINE.md)

| Filing | Reviewed row nominated | Final row | First stop |
| --- | --- | --- | --- |
| Mastercard FY2024 | No | `table-64/row-16` | Unsupported consolidated scope |
| Oracle FY2024 | Yes | `table-76/row-15` | Unsupported consolidated scope |
| PepsiCo FY2024 | Yes | `table-28/row-3` | Selected the reviewed row. The extractor requires a shared fiscal year-end. |
| Adobe FY2017 | No | `table-128/row-7` | Unsupported consolidated scope |
| Adobe FY2024 | Yes | `table-32/row-8` | Selected the reviewed row. Three amounts remained provisional with unknown period starts. |
| eBay FY2024 | No | `table-42/row-6` | Unsupported consolidated scope |
| Salesforce FY2024 | No | `table-81/row-48` | Unsupported consolidated scope |

The **absent-target** control contains a consolidated income statement
without a revenue row and a segment revenue table. The model picked the
statement's units row. The shared extractor rejected it and emitted zero
observations. The model missed the expected explicit abstention. In the
**distractor** control, the model chose total revenues beside a net sales
subtotal and segment revenue. The extractor retained two provisional
observations of USD 15 million for FY2023 and USD 19 million for FY2024.
[Absent-target original](../../tests/fixtures/revenue-selection-absent.html) ·
[Distractor original](../../tests/fixtures/revenue-selection-distractor.html)

## Batch and replay record

The model sees the shared parsed inventory in original order. Each request
contains table IDs and nearby context, followed by stable row IDs and visible
cell text. Table context is limited to 600 UTF-8 bytes after JSON escaping.
Row text exceeding 850 bytes after escaping is split while retaining its
row ID, and empty tables are included.
Each batch has a 7,600-byte combined system and user message cap within an
8,192-token runtime context. The full cell grid, spans and XBRL evidence are
available in the rules-baseline inventory and the deterministic extractor.

In an initial development pass, out-of-batch IDs stopped six filings.
The retained run uses a grammar permitting the listed row IDs and an
explicit abstention. It records 160 calls across the filings and controls,
including two explicit batch abstentions and zero invalid responses.
The selector also checks each response against the batch. A failed batch
prevents accepting a nomination from that filing. Multiple nominations enter
further bounded comparison batches in source order. The final pair reaches
the same original-cell, period, currency, scale and scope checks as rules
alone. Reviewed row IDs and amounts enter only during independent scoring.

Selection and validation for the seven originals took 60.1 seconds in total
on Windows with llama.cpp b6500 and an NVIDIA RTX 5060 Laptop GPU using Vulkan.
The cumulative Python and server peak working sets were 72 MiB and 1,621 MiB.
Device memory samples were 1,517–1,518 MiB. These are device-wide point
samples, and peak VRAM was unmeasured. Offline replay reproduced the
batch membership, decisions, stops and observations for all nine cases.
[Model trace and settings](revenue-selection-model/run.json.gz)

## Reproduce on Windows

Run from the repository root with the locked Python environment, the local
opened #54 archives, and the pinned GGUF at
`.frag-model/qwen2.5-1.5b-instruct-q4_k_m.gguf`. The runner verifies the
weights hash before starting llama.cpp on loopback and checks a
run-specific model alias as part of readiness and response validation.
[Opened archive custody](CONTINUATION_HOLDOUT.md)

The pinned GGUF is Apache-2.0 and llama.cpp b6500 is MIT.
[Qwen GGUF revision](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/tree/91cad51170dc346986eccefdc2dd33a9da36ead9) ·
[llama.cpp license](https://github.com/ggml-org/llama.cpp/blob/b6500/LICENSE)

For the measured Windows setup, unpack `llama-b6500-bin-win-vulkan-x64.zip`
with SHA-256 `d485ce9cdda9967d2b27a054bb7e16b57a56a332a4b54b2f02964b95ee591548`
into `build/llama-b6500-vulkan`. Set `--device` to the NVIDIA device
reported by `llama-server.exe --list-devices`. The measured host used
`Vulkan1`. The runner also supports the cached CPU runtime by omitting
`--runtime`, `--gpu-layers` and `--device`.
[llama.cpp b6500 release](https://github.com/ggml-org/llama.cpp/releases/tag/b6500)

```powershell
$custody = '../FRAG-SEC-Holdout-54'
$run = "build/revenue-selection-57-$([guid]::NewGuid())"
$runtime = 'build/llama-b6500-vulkan/llama-server.exe'
.venv/Scripts/python.exe artifacts/phase06/revenue_selection_model.py "$custody/runner/inputs.zip" $run --runtime $runtime --gpu-layers 99 --device Vulkan1 --port 18099
if ($LASTEXITCODE -ne 0) { throw 'Local model run failed.' }
.venv/Scripts/python.exe artifacts/phase06/revenue_selection_model_score.py "$custody/runner/inputs.zip" "$custody/scorer/expected.zip" "$run/run.json.gz" "$run/score.json"
if ($LASTEXITCODE -ne 0) { throw 'Offline replay and scoring failed.' }
Get-Content "$run/score.json"
```

To replay the checked-in model responses without loading weights, use
the saved trace as input. The replay command blocks socket operations.

```powershell
$custody = '../FRAG-SEC-Holdout-54'
$saved = 'artifacts/phase06/revenue-selection-model'
$score = "build/revenue-selection-57-score-$([guid]::NewGuid()).json"
.venv/Scripts/python.exe artifacts/phase06/revenue_selection_model_score.py "$custody/runner/inputs.zip" "$custody/scorer/expected.zip" "$saved/run.json.gz" $score
if ($LASTEXITCODE -ne 0) { throw 'Retained replay failed.' }
if ((Get-FileHash $score).Hash -ne (Get-FileHash "$saved/score.json").Hash) { throw 'Retained score differs.' }
```
