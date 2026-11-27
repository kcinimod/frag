# Issuer-disjoint SEC revenue extraction comparison

Retain **rules alone** for the extraction experiment. Neither Qwen2.5
strategy improved overall exact extraction or improved any issuer family.
Rules alone and the shortlisted model reproduced the same nine exact
observations, all provisional under the existing verification policy.
[Issue #60](https://github.com/kcinimod/frag/issues/60) ·
[Independent score](revenue-selection-acceptance/score.json) ·
[Run and selector diagnostics](revenue-selection-acceptance/run.json.gz)

| Strategy | Exact observations | Reviewed row available | Wrong selections before validation | Incorrect observations retained | Absent-target abstentions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rules alone | 9/12 | 3/4 | 0/6 | 0 | 2/2 |
| Model only | 0/12 | 4/4 | 6/6 | 0 | 0/2 |
| Rules-shortlisted model | 9/12 | 3/4 | 0/6 | 0 | 2/2 |

Candidate availability means inclusion in the rules candidate list or
submission in an initial model batch. The Kroger reviewed row appeared in
the broad inventory and was omitted by financial shortlisting. The model
only strategy chose a different row for every filing and both controls.
The shared validator rejected all six choices on scope.

| Issuer family or control | Rules alone | Model only | Rules-shortlisted model |
| --- | ---: | ---: | ---: |
| Visa | 3/3 | 0/3 | 3/3 |
| FedEx | 3/3 | 0/3 | 3/3 |
| Berkshire Hathaway | 3/3 | 0/3 | 3/3 |
| Kroger | 0/3 | 0/3 | 0/3 |
| IBM, Item 8 in a separate exhibit | Abstained | Wrong row | Abstained |
| Northwind Components, synthetic division distractor | Abstained | Wrong row | Abstained |

## Windows measurements

| Strategy | Model calls | Parse time | Selection and validation | Worker wall time | Python peak RAM | Server peak RAM | Sampled peak VRAM |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Rules alone | 0 | 1.991 s | 0.049 s | 3.845 s | 169 MiB | — | 0 MiB |
| Model only | 117 | 2.651 s | 60.085 s | 70.431 s | 171 MiB | 2,000 MiB | 1,518 MiB |
| Rules-shortlisted model | 3 | 2.578 s | 7.834 s | 18.258 s | 170 MiB | 1,499 MiB | 1,511 MiB |

Each strategy ran in a fresh Windows process on the same host. The model
strategies also started fresh servers on the RTX 5060 Laptop GPU. Worker wall
time includes startup and candidate serialization. RAM figures are separate
Windows peak working sets. VRAM is the maximum device-wide NVIDIA sample
observed at a requested 50 ms interval, including startup, with a 0 MiB
starting sample for every strategy. Transient peaks between samples may be
higher. The three raw sampling traces are retained with their hashes.

## Freeze and custody

The #59 audit reopened the original byte spans, checked physical fiscal and
value-cell alignment, corroborated amounts and full periods against the saved
SEC Company Facts, and verified both archive seals. The final inventory
retained 35 originals from 30 known issuer families. Between the preparation
base and the frozen development revision, the tracked changes covered custody
tooling, its tests, and documentation. The final CIK, accession, alias, and
source-hash overlap with the held-out issuer families was zero.

The selectors received only the runner archive. The scoring archive stayed
separate. All three strategies used identical parsed inventories, as checked
by the per-filing inventory hashes and replay. The model strategies used the
same Qwen2.5 1.5B Instruct Q4_K_M weights, llama.cpp b6500 Vulkan runtime,
temperature zero, seed zero, grammar, and batch budgets. The full settings,
code and runtime hashes, seals, and adoption thresholds are in the freeze.
[Custody and independent review](REVENUE_SELECTION_HOLDOUT.md) ·
[Freeze](revenue-selection-acceptance/freeze.json) ·
[Final development inventory](revenue-selection-acceptance/final-development-inventory.json)

The gate required strict overall improvement over rules alone, improvement
in at least two independent issuer families, zero incorrect accepted
observations, and abstention on both absent-target controls. The frozen score
counts every retained non-exact observation against the zero-error gate,
including provisional observations. An absent-target abstention requires
no selection, no retained observations, and a valid abstention stop.

## Reproduce on Windows

Run from the repository root in the locked project Python environment. The
live run uses the retained freeze, the independently sealed runner bundle,
and the weights and Vulkan build used for the development comparison. Live
measurements require the original Windows host, GPU, and driver pinned in the
freeze. Check the retained manifest and freeze before starting the selectors.
The scorer also uses the sealed scorer bundle. Its replay blocks socket
operations and checks every saved model response against its original prompt
hash, batch membership, and deterministic extraction output.
[Runtime setup](REVENUE_SELECTION_MODEL.md#reproduce-on-windows) ·
[Artifact checksums](revenue-selection-acceptance/SHA256SUMS)

```powershell
$custody = '../FRAG-SEC-Holdout-59'
$saved = 'artifacts/phase06/revenue-selection-acceptance'
$script = 'artifacts/phase06/revenue_selection_acceptance.py'
$runtime = 'build/llama-b6500-vulkan/llama-server.exe'
$weights = '.frag-model/qwen2.5-1.5b-instruct-q4_k_m.gguf'
$run = "build/revenue-selection-60-$([guid]::NewGuid())"
foreach ($line in Get-Content "$saved/SHA256SUMS") {
    $digest, $name = $line -split '  ', 2
    if ((Get-FileHash "$saved/$name").Hash -ne $digest) { throw "Hash mismatch for $name." }
}
.venv/Scripts/python.exe $script run "$saved/freeze.json" "$custody/runner/inputs.zip" $run $runtime $weights
if ($LASTEXITCODE -ne 0) { throw 'Frozen comparison failed.' }
.venv/Scripts/python.exe $script score "$saved/freeze.json" "$custody/runner/inputs.zip" "$custody/scorer/expected.zip" "$run/run.json.gz" "$run/score.json"
if ($LASTEXITCODE -ne 0) { throw 'Comparison scoring failed.' }
```

Replay the retained result without loading weights or running a server.

```powershell
$custody = '../FRAG-SEC-Holdout-59'
$saved = 'artifacts/phase06/revenue-selection-acceptance'
$script = 'artifacts/phase06/revenue_selection_acceptance.py'
New-Item -ItemType Directory -Path build -Force | Out-Null
$score = "build/revenue-selection-60-score-$([guid]::NewGuid()).json"
.venv/Scripts/python.exe $script score "$saved/freeze.json" "$custody/runner/inputs.zip" "$custody/scorer/expected.zip" "$saved/run.json.gz" $score
if ($LASTEXITCODE -ne 0) { throw 'Offline replay failed.' }
if ((Get-FileHash $score).Hash -ne (Get-FileHash "$saved/score.json").Hash) { throw 'Score differs from the retained result.' }
```
