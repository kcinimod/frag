# Phase 5 verified revenue growth

Issue #30 establishes comparison compatibility for the latest two reported
annual periods in the supported original-evidence layouts. Both observations
must pass their own checks. The verifier checks that the periods are
consecutive and that the revenue cells use the same inline XBRL concept.
An explicit disclosure that qualifies consolidated revenue comparability
withholds growth and can be opened from the partial result. The comparison
check leaves the verified amounts available for individual lookup.
[Issue #30](https://github.com/kcinimod/frag/issues/30)

## Filing results

| Filing | Prior fiscal year | Current fiscal year | Reported revenue growth |
| --- | ---: | ---: | ---: |
| Microsoft control | 2022 | 2023 | 6.88% |
| Apple control | 2022 | 2023 | −2.80% |
| Amazon | 2022 | 2023 | 11.83% |
| Walmart | 2023 | 2024 | 6.03% |
| Alphabet | 2022 | 2023 | 8.68% |
| Intel | 2022 | 2023 | −14.00% |

Intel reported USD 63,054 million for the 53 weeks through December 31, 2022
and USD 54,228 million for the 52 weeks through December 30, 2023. Chrome
matched the offline CLI calculation and reopened both statement cells, the
fiscal calendar disclosure, and the revenue recognition disclosure. Asking
for equal-length fiscal years withheld the percentage, explained the duration
difference, and reopened the same four citations.
[Chrome run](verified-growth-browser.txt)

The fixed development comparison improved from 8/13 to 12/13 correct numeric
answers and from 8/15 to 13/15 end-to-end completions per pass. Grounded
abstentions increased from 1/2 to 2/2. All 30 cold and warm results and
citations matched in offline replay. The emitted numeric answers passed
the independent citation checks in 11 of 12 cases. Microsoft's growth cells
still open at their original locators and omit the original USD measure in
the excerpt, a limitation also recorded in #29. The Apple FY2024 lookup
remains provisional.
[Previous checkpoint](DEVELOPMENT_LAYOUTS.md) ·
[Freeze](verified-growth-freeze.json) ·
[Live records](verified-growth-live.json.gz) ·
[Offline replay](verified-growth-replay.json.gz) ·
[Per-case scores](verified-growth-score.json)

Collection regressions cover Intel's supported pair, a pair outside the
filing's verified comparison, and the equal-length constraint in one-pass
and bounded modes. They open the original citations and replay saved CLI
records with sockets blocked. Synthetic mutations cover two independent
observations with different revenue tags and an explicit disclosure of
incompatible gross and net reporting.
[Growth regressions](../../tests/test_unseen_revenue.py)

## Replay on Windows

Run from the repository root with the locked Python environment installed.
To check the built browser with installed Chrome, run the commands below.
The browser routes requests to a temporary local server. The CLI subprocess
blocks sockets and the browser replay raises an error if it calls the planner.

```powershell
npm.cmd --prefix web run build
uv run --locked --offline --with playwright python artifacts/phase05/growth_browser.py
.venv/Scripts/python.exe -m pytest -q
```

For the retained planner run, recreate the frozen revision, replay with
network access blocked, and score against the independent development
references.

```powershell
$ErrorActionPreference = 'Stop'
$repo = (Get-Location).Path
$revision = '96cec931a40d34ce50acac2a2c04e8c91093e352'
$snapshot = & artifacts/phase05/snapshot.ps1 -Destination (Join-Path 'build' ('issue30-replay-' + [guid]::NewGuid()))
$files = @(git diff --name-only f62d21a $revision -- src/frag)
git -c core.autocrlf=false archive --format=zip --output="$snapshot/candidate.zip" $revision -- @files
if ($LASTEXITCODE -ne 0) { throw 'Candidate export failed.' }
Expand-Archive -LiteralPath "$snapshot/candidate.zip" -DestinationPath $snapshot -Force
Copy-Item -LiteralPath artifacts/phase05/verified-growth-freeze.json -Destination "$snapshot/freeze.json"
.venv/Scripts/python.exe -c "import gzip, pathlib, sys; pathlib.Path(sys.argv[2]).write_bytes(gzip.decompress(pathlib.Path(sys.argv[1]).read_bytes()))" artifacts/phase05/verified-growth-live.json.gz "$snapshot/live.json"
if ($LASTEXITCODE -ne 0) { throw 'Could not unpack the live run.' }
$runner = Join-Path $snapshot 'artifacts/phase05/baseline.py'
.venv/Scripts/python.exe $runner replay --data $snapshot --freeze "$snapshot/freeze.json" --work "$snapshot/replay" --live "$snapshot/live.json"
if ($LASTEXITCODE -ne 0) { throw 'Offline replay failed.' }
.venv/Scripts/python.exe artifacts/phase05/score.py $repo "$snapshot/live.json" "$snapshot/replay/report.json" "$snapshot/score.json"
if ($LASTEXITCODE -ne 0) { throw 'Scoring failed.' }
```
