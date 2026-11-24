# Phase 5 unseen-issuer revenue lookup

Issue #28 adds verification for consolidated income statements with annual
columns under a shared fiscal year-end. Verification checks the company above
the statement against the inline cover, then checks each revenue cell against
its annual, undimensioned SEC CIK context and its USD unit, scale, and amount.
The accounting policies supply original evidence for consolidation and revenue
recognition. A supported visible observation can remain provisional when the
tag or disclosures do not establish agreement.
[Issue #28](https://github.com/kcinimod/frag/issues/28)

| Filing | Verified lookup | Visible statement layout |
| --- | ---: | --- |
| Amazon FY2023 10-K | USD 574,785,000,000 | Ascending years, scale above the table, total net sales |
| Alphabet FY2023 10-K | USD 307,394,000,000 | Ascending years, scale in the table wrapper, revenues |
| Walmart FY2024 10-K | USD 648,125,000,000 | Descending years, scale in a header cell, total revenues |

Each lookup opens the original issuer heading, revenue cell and row,
annual and year headers, scale and currency, and accounting-policy
citations. Walmart’s recognition citation also covers membership fees.
The filing-scoped workflow still checks the proposed plan against the
independently resolved request and eligible facts.

## Fixed development comparison

Both runs use the same 15 questions, seven preserved filings, independent
expected observations and locators, and Qwen2.5-0.5B-Instruct Q4_K_M planner
with the frozen runtime, generation, and retrieval settings. Each stage
score counts requested observations, including repeated observations across
questions. The extraction score requires the expected amount, period,
currency, scale, scope, and original statement cell. The verification score
requires a verified status as well.
[Baseline inputs and run](README.md) · [Lookup run freeze](unseen-lookup-freeze.json)

| Measure | Baseline | Shared year-end lookup |
| --- | ---: | ---: |
| Requested observations extracted at the expected locator | 8/22 | 17/22 |
| Requested observations verified | 7/22 | 16/22 |
| Correct numeric answers | 4/13 | 7/13 |
| Original citation support among emitted numeric answers | 2/4 | 5/7 |
| Grounded abstentions | 1/2 | 1/2 |
| End-to-end completions | 3/15 | 6/15 |
| Identical results and citations on offline replay, cold plus warm | 30/30 | 30/30 |

Cold and warm passes produced identical scores. The Apple FY2024 lookup
counts toward extraction and remains provisional. Amazon, Alphabet, and
Walmart growth questions preserve both verified observations and their
citations while comparison compatibility is unresolved. Intel’s differently
formatted statement remains outside this parser’s coverage. This is a
development checkpoint. Fresh holdout measurement is pending.
[Per-case stage scores](unseen-lookup-score.json) ·
[Live records and original excerpts](unseen-lookup-live.json.gz) ·
[Offline replay](unseen-lookup-replay.json.gz)

Median question latency was 394.2 ms cold and 368.7 ms warm, including
citation opening. Peak working sets were 573.68 MiB for the planner and
88.80 MiB for the runner. The sampled device VRAM peak was 0 MiB with GPU
offload set to zero. Chrome independently displayed Amazon’s answer and
opened all three citations with the planner stopped.
[Chrome run](unseen-lookup-browser.txt)

## Replay on Windows

Run from the repository root after installing the locked Python environment.
These commands export the measured Python changes over the frozen baseline,
replay the recorded CLI calls with sockets blocked, reopen the original
browser citation routes, and rescore against the independent expectations.

```powershell
$ErrorActionPreference = 'Stop'
$revision = '2c5d2b1b5db1913828f4a88b1646de87df4d02c8'
$repo = (Get-Location).Path
$snapshot = & artifacts/phase05/snapshot.ps1 -Destination (Join-Path 'build' ('issue28-' + [guid]::NewGuid()))
$files = @(git diff --name-only f62d21a $revision -- src/frag)
git -c core.autocrlf=false archive --format=zip --output="$snapshot/lookup.zip" $revision -- @files
if ($LASTEXITCODE -ne 0) { throw 'Candidate export failed.' }
Expand-Archive -LiteralPath "$snapshot/lookup.zip" -DestinationPath $snapshot -Force
Copy-Item -LiteralPath artifacts/phase05/unseen-lookup-freeze.json -Destination "$snapshot/freeze.json"
.venv/Scripts/python.exe -c "import gzip, pathlib, sys; pathlib.Path(sys.argv[2]).write_bytes(gzip.decompress(pathlib.Path(sys.argv[1]).read_bytes()))" artifacts/phase05/unseen-lookup-live.json.gz "$snapshot/live.json"
if ($LASTEXITCODE -ne 0) { throw 'Could not unpack the live run.' }
$runner = Join-Path $snapshot 'artifacts/phase05/baseline.py'
.venv/Scripts/python.exe $runner replay --data $snapshot --freeze "$snapshot/freeze.json" --work "$snapshot/replay" --live "$snapshot/live.json"
if ($LASTEXITCODE -ne 0) { throw 'Replay failed.' }
.venv/Scripts/python.exe artifacts/phase05/score.py $repo "$snapshot/live.json" "$snapshot/replay/report.json" "$snapshot/score.json"
if ($LASTEXITCODE -ne 0) { throw 'Scoring failed.' }
```

To collect a new live pass instead, use a fresh snapshot and the pinned
model and llama.cpp package from the baseline instructions. Run the
benchmark with the retained lookup freeze. The live runner uses the local
planner over IPv4 loopback on port 18089.

```powershell
$model = (Resolve-Path '.frag-model').Path
.venv/Scripts/python.exe $runner live --data $snapshot --freeze "$snapshot/freeze.json" --model $model --work "$snapshot/live"
if ($LASTEXITCODE -ne 0) { throw 'Live run failed.' }
```
