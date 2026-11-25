# Phase 5 revenue evidence gaps

Issue #31 bases absence claims on the consolidated revenue statement and
its displayed fiscal-year columns. A statement period can be established
independently of whether extraction and verification establish an amount.
Growth results retain verified companion amounts and their original citations.
[Issue #31](https://github.com/kcinimod/frag/issues/31)

| Filing and request | Original evidence | CLI and Chrome result |
| --- | --- | --- |
| Apple FY2023 10-K, FY2020 lookup or FY2020 to FY2023 growth | The consolidated statement lists September 25, 2021, September 24, 2022, and September 30, 2023. | Reports FY2020 absent from the statement and links to the period headers. Growth displays the verified FY2023 amount of USD 383,285 million and opens its cell and three disclosures. |
| Microsoft FY2023 10-K, FY2021 to FY2023 growth | The FY2021 column reports USD 168,088 million. The extractor selects FY2022 and FY2023. | Reports an extraction gap for FY2021 and displays the verified FY2023 amount of USD 211,915 million with its cell and four disclosures. |
| Apple FY2024 10-K, FY2024 lookup | The statement reports USD 391,035 million on September 28, 2024. The reviewed reference is for the FY2023 filing. | Reports a verification gap and explains that the original has yet to be matched to a reviewed reference and its applicable disclosures need verification. |
| Intel FY2023 10-K, FY2022 to FY2023 growth using equal-length fiscal years | The original discloses a 53-week FY2022 and a 52-week FY2023. | Withholds the percentage and opens both verified amounts and the applicable disclosures. |

The browser check uses the independently reviewed original spans and compares
the browser results with socket-blocked CLI results and CLI replay. A synthetic
regression moves a period to a separate header row and blanks its total.
Another inserts a conflicting period label beneath an existing column. The
CLI reports an evidence gap for both layouts.
The retained Microsoft FY2022 10-K also distinguishes FY2019 absence from
the displayed but unextracted FY2020. New evidence-gap records use validation
record version 5. The six cold and warm issue #30 records for the three fixed
abstention and verification-gap cases also reproduced their historical
outcomes on the current revision.
[Browser check](evidence_gap_browser.py) · [Chrome run](evidence-gap-browser.txt) ·
[Original evidence labels](expected.json)

## Fixed development comparison

Both revisions ran the same 15 questions against seven preserved originals.
The model weights, runtime, planner settings, retrieval configuration, and
reviewed labels matched the issue #30 freeze. Cold and warm scores agreed.

| Measure | Issue #30 | Issue #31 |
| --- | ---: | ---: |
| Correct numeric answers | 12/13 | 12/13 |
| Original citation support among emitted numeric answers | 11/12 | 11/12 |
| Grounded abstentions | 2/2 | 2/2 |
| End-to-end completions | 13/15 | 13/15 |
| Offline result and citation matches across both passes | 30/30 | 30/30 |

For the fixed Apple FY2020 growth question, the previous evidence gap now
identifies the absent year with a statement-period citation. The FY2024
lookup explains the reviewed-reference and disclosure checks that remain
open. Candidate median question latency with citation opening was
1,708.5 ms cold and 1,747.5 ms warm. Peak working sets were 578.66 MiB for
the planner and 89.16 MiB for the runner. Sampled device VRAM peaked at 0 MiB.
Microsoft's calculated growth still opens the original cells with
the USD measure omitted from the excerpt, so the scorer withholds citation
credit for that answer.
[Previous checkpoint](VERIFIED_GROWTH.md) ·
[Freeze](evidence-gap-freeze.json) ·
[Live records](evidence-gap-live.json.gz) ·
[Offline replay](evidence-gap-replay.json.gz) ·
[Per-case scores](evidence-gap-score.json)

## Windows browser and CLI checks

```powershell
npm.cmd --prefix web run build
uv run --locked --offline --with playwright python artifacts/phase05/evidence_gap_browser.py
uv run --locked --offline --with playwright python artifacts/phase05/growth_browser.py
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe -m pytest -q
```

## Replay the fixed development questions

This recreates the measured production revision outside the working tree.
The replay opens citations against the original bytes and blocks all network
connections. The scorer uses the same reviewed reference as issue #30.

```powershell
$ErrorActionPreference = 'Stop'
$repo = (Get-Location).Path
$revision = '7c558e27ae0ff9a3ca0fc32af68d6e80a55b3390'
$snapshot = & artifacts/phase05/snapshot.ps1 -Destination (Join-Path 'build' ('issue31-replay-' + [guid]::NewGuid()))
$files = @(git diff --name-only f62d21a $revision -- src/frag)
git -c core.autocrlf=false archive --format=zip --output="$snapshot/candidate.zip" $revision -- @files
if ($LASTEXITCODE -ne 0) { throw 'Candidate export failed.' }
Expand-Archive -LiteralPath "$snapshot/candidate.zip" -DestinationPath $snapshot -Force
Copy-Item -LiteralPath artifacts/phase05/evidence-gap-freeze.json -Destination "$snapshot/freeze.json"
.venv/Scripts/python.exe -c "import gzip, pathlib, sys; pathlib.Path(sys.argv[2]).write_bytes(gzip.decompress(pathlib.Path(sys.argv[1]).read_bytes()))" artifacts/phase05/evidence-gap-live.json.gz "$snapshot/live.json"
if ($LASTEXITCODE -ne 0) { throw 'Could not unpack the live run.' }
$runner = Join-Path $snapshot 'artifacts/phase05/baseline.py'
.venv/Scripts/python.exe $runner replay --data $snapshot --freeze "$snapshot/freeze.json" --work "$snapshot/replay" --live "$snapshot/live.json"
if ($LASTEXITCODE -ne 0) { throw 'Offline replay failed.' }
.venv/Scripts/python.exe artifacts/phase05/score.py $repo "$snapshot/live.json" "$snapshot/replay/report.json" "$snapshot/score.json"
if ($LASTEXITCODE -ne 0) { throw 'Scoring failed.' }
```
