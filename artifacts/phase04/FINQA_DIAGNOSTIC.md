# FinQA annotated-evidence diagnostic

Issue #18 covers a dev checkpoint on [13 official dev questions](finqa-dev-cohort.json).
The cohort was selected before inference to cover all ten FinQA operations,
single-step and multi-step programs, both comparison outcomes, and evidence
from text, tables, or both. It is a coverage sample for inspecting failure
modes. The run used zero demonstrations.

The local model produced three executable plans. Two matched the reference
execution answer. One averaged a table row when the question required a
division. Validation rejected the other ten plans for unsupported operands
or invalid table references. All 13 outcomes replayed after the local
server stopped, with every selected excerpt fitting the context budget.
The `2/13` result is an internal answer-match count for this coverage
sample. Upstream scoring parity and public-test evaluation are pending.

The [saved run](finqa-dev-run.json) records the upstream revision and hashes,
the overlap audit, the model identity, and one record per question. Inspect
`source_excerpts` for the original dataset text and table cells,
`planner_input.messages` for the delivered question and context, and
`omitted_excerpt_ids` for excerpts dropped under the 2,800 UTF-8 byte
user-message budget. The `reference` object contains the scoring labels.
`proposal` holds the model response verbatim. `outcome` records the
validation status, any completed steps and operand sources, and the final
value or failure reason.

The split audit found no shared question IDs, source page names, or exact
report content across split pairs. It counted shared distinct issuer/year
paths and shared normalized question strings, as shown below. Membership
follows the pinned upstream files.

| Split pair | Shared issuer/year paths | Shared normalized question strings |
| --- | ---: | ---: |
| Train/dev | 197 | 16 |
| Train/public test | 243 | 7 |
| Dev/public test | 93 | 2 |

## Offline replay

Run from the repository root with the existing Python environment. Replay
rebuilds the planner input and revalidates and reexecutes the saved proposals
from the record. A recorded transport failure replays as its recorded
status. The output is JSON.

```powershell
.venv/Scripts/python.exe -m frag.finqa replay artifacts/phase04/finqa-dev-run.json
```

## Fresh run on Windows

Use the pinned files from the [FinQA upstream revision](https://github.com/czyssrs/FinQA/tree/0f16e2867befa6840783e58be38c9efb9229d742).
The download step fetches the files once. If downloads are unavailable, place
the same bytes in `build/finqa`. Running the diagnostic checks the hashes of
the three split files before reading question IDs or calling the planner.
The pinned upstream evaluator is retained in the download cache for future
scoring parity work.

```powershell
$ErrorActionPreference = 'Stop'
$revision = '0f16e2867befa6840783e58be38c9efb9229d742'
$base = "https://raw.githubusercontent.com/czyssrs/FinQA/$revision"
$cache = 'build/finqa'
New-Item -ItemType Directory -Force $cache | Out-Null
foreach ($name in 'dataset/train.json','dataset/dev.json','dataset/test.json','code/evaluate/evaluate.py','code/generator/constant_list.txt','code/generator/operation_list.txt','LICENSE','README.md') {
    $destination = Join-Path $cache (Split-Path $name -Leaf)
    curl.exe -fLsS "$base/$name" -o $destination
    if ($LASTEXITCODE) { throw "Unable to fetch $name" }
}
Get-ChildItem $cache -File | Get-FileHash
```

With the repository's local planner installed, use the current runtime
configuration to generate a fresh record. The saved run identifies the
Qwen2.5-1.5B-Instruct Q4_K_M configuration available in the working tree
when it was recorded. Fresh plans can vary with a different model
configuration. Offline replay uses the saved requests and responses.

```powershell
$record = Join-Path 'build' ("finqa-dev-" + [guid]::NewGuid().ToString() + ".json")
$planner = & .\scripts\start-local-model.ps1 -Background
try {
    if (!(Test-NetConnection 127.0.0.1 -Port 8087 -InformationLevel Quiet)) { throw 'Local planner did not start' }
    .venv/Scripts/python.exe -m frag.finqa run build/finqa $record --cohort artifacts/phase04/finqa-dev-cohort.json
    if ($LASTEXITCODE) { throw 'FinQA diagnostic failed' }
} finally {
    Stop-Process -Id $planner.Id -ErrorAction SilentlyContinue
}
.venv/Scripts/python.exe -m frag.finqa replay $record
```

Run the diagnostic's synthetic CLI checks and repository type check.

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_finqa_workflow.py
.venv/Scripts/python.exe -m mypy
```

The retained FinQA excerpts carry the [upstream MIT license](FINQA_LICENSE.txt).
