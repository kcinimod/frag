# Phase 5 development layout verification

Issue #29 verifies Intel’s annual reported consolidated revenue from a
statement with a separate title table, abbreviated full dates, and units in
the annual header. The verifier checks the displayed cells against
undimensioned SEC CIK contexts and USD inline XBRL. Note 1 establishes the
issuer, consolidation, and fiscal calendar. Note 2 establishes revenue
recognition, variable consideration, and when cooperative advertising
payments are recorded as reductions in revenue. A disclosure that names a
specific fiscal year withholds that observation while the other years can
still qualify through their own evidence.
[Issue #29](https://github.com/kcinimod/frag/issues/29)

| Filing | Annual statement layout | FY | Verified USD millions | Original table / row / cell | Verification |
| --- | --- | ---: | ---: | --- | --- |
| Microsoft | Shared year-end and descending years | 2023 | 211,915 | 25 / 12 / 4 | Reviewed reference |
| Apple | Separate full dates and units above the table | 2023 | 383,285 | 23 / 7 / 2 | Reviewed reference |
| Amazon | Shared year-end and ascending years, units above the table | 2023 | 574,785 | 38 / 6 / 8 | Original evidence |
| Walmart | Shared year-end and descending years, units in the header | 2024 | 648,125 | 50 / 7 / 3 | Original evidence |
| Alphabet | Shared year-end and ascending years, units in the table wrapper | 2023 | 307,394 | 84 / 4 / 11 | Original evidence |
| Intel | Separate title table, full dates and units in the same row | 2023 | 54,228 | 156 / 3 / 4 | Original evidence |

All six filing-scoped lookups met the original-cell, currency, scale, and
disclosure checks. Microsoft’s lookup now opens four reviewed notes and
includes the original USD measure in its statement excerpt. Saved Microsoft
lookup records retain their original citation format on replay. Chrome
rendered Intel’s result and reopened its statement and both notes with the
planner stopped. [Chrome run](development-layout-browser.txt)

## Paired development runs

Both revisions ran the same 15 questions against seven preserved originals.
The planner, runtime, generation and retrieval configuration, and independent
scoring references had identical hashes or values in both freezes. Cold and
warm scores agreed.
[Previous freeze and run](UNSEEN_LOOKUP.md) ·
[Candidate freeze](development-layout-freeze.json)

| Measure | Issue #28 | Issue #29 |
| --- | ---: | ---: |
| Requested observations extracted at the expected locator | 17/22 | 22/22 |
| Requested observations verified | 16/22 | 21/22 |
| Verified observations using original evidence checks | 9 | 14 |
| Verified observations using reviewed references | 7 | 7 |
| Correct numeric answers | 7/13 | 8/13 |
| Original citation support among emitted numeric answers | 5/7 | 7/8 |
| End-to-end completions | 6/15 | 8/15 |
| Grounded abstentions | 1/2 | 1/2 |
| Offline result and citation matches across cold and warm runs | 30/30 | 30/30 |

Observation counts include repeated requests for the same period. The
retained reports include source hashes, fact and disclosure locators,
provisional requirements, planner input and output, and the text opened
through the browser citation routes. Median question latency, including
citation opening, was 1,597.7 ms cold and 1,622.1 ms warm. The planner and
runner peak working sets were 573.70 MiB and 88.82 MiB. Sampled device VRAM
peaked at 0 MiB with CPU inference.
[Per-case scores](development-layout-score.json) ·
[Live records](development-layout-live.json.gz) ·
[Offline replay](development-layout-replay.json.gz)

Apple FY2024 remains provisional at USD 391,035 million pending applicable
disclosure verification for that filing. Ordinary growth for Amazon,
Alphabet, Walmart, and Intel returns the two cited observations while
comparison compatibility remains unresolved. Intel’s equal-length growth
question still returns clarification. The original Microsoft growth
citations reopen, but the growth cell excerpts lack the USD evidence
required by the frozen scorer.

## Collection lookup

The issue #28 revision raised `KeyError: interpretation` on the full
development store. The index now accepts original notes with a title and
locator alone. All six questions returned the expected amount through
`ask-collection`, matched the browser response and `replay-collection`,
and reopened all 21 returned citations with sockets blocked.
[Paired collection records](development-layout-collection.json.gz)

## Replay on Windows

From the repository root, use the locked Python environment. The script
recreates the measured revision, replays the saved CLI calls, opens the
original browser citation routes, and scores them against the same reference.

```powershell
$ErrorActionPreference = 'Stop'
$repo = (Get-Location).Path
$revision = '66005dc3526f92dc9d89771c5757d670a6a9aff2'
$snapshot = & artifacts/phase05/snapshot.ps1 -Destination (Join-Path 'build' ('issue29-replay-' + [guid]::NewGuid()))
$files = @(git diff --name-only f62d21a $revision -- src/frag)
git -c core.autocrlf=false archive --format=zip --output="$snapshot/candidate.zip" $revision -- @files
if ($LASTEXITCODE -ne 0) { throw 'Candidate export failed.' }
Expand-Archive -LiteralPath "$snapshot/candidate.zip" -DestinationPath $snapshot -Force
Copy-Item -LiteralPath artifacts/phase05/development-layout-freeze.json -Destination "$snapshot/freeze.json"
.venv/Scripts/python.exe -c "import gzip, pathlib, sys; pathlib.Path(sys.argv[2]).write_bytes(gzip.decompress(pathlib.Path(sys.argv[1]).read_bytes()))" artifacts/phase05/development-layout-live.json.gz "$snapshot/live.json"
if ($LASTEXITCODE -ne 0) { throw 'Could not unpack the live run.' }
$runner = Join-Path $snapshot 'artifacts/phase05/baseline.py'
.venv/Scripts/python.exe $runner replay --data $snapshot --freeze "$snapshot/freeze.json" --work "$snapshot/replay" --live "$snapshot/live.json"
if ($LASTEXITCODE -ne 0) { throw 'Offline replay failed.' }
.venv/Scripts/python.exe artifacts/phase05/score.py $repo "$snapshot/live.json" "$snapshot/replay/report.json" "$snapshot/score.json"
if ($LASTEXITCODE -ne 0) { throw 'Scoring failed.' }
$collection = Join-Path $snapshot 'artifacts/phase05/collection_lookup.py'
Copy-Item -LiteralPath artifacts/phase05/collection_lookup.py -Destination $collection
.venv/Scripts/python.exe $collection "$snapshot/replay/store" "$snapshot/collection.json"
if ($LASTEXITCODE -ne 0) { throw 'Collection check failed.' }
```

For the before-revision collection run, reproduce the issue #28 snapshot
and offline replay from its checkpoint, copy the same collection script
into that snapshot, and pass its replay store. [Issue #28 replay](UNSEEN_LOOKUP.md#replay-on-windows)
