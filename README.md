# FRAG

Local, evidence-first SEC financial QA work in progress. The CLI and browser
workspace preserve original source bytes and expose verified and provisional consolidated
revenue for FY2022 and FY2023 from the selected Microsoft FY2023 10-K.

From the repository root in Windows PowerShell, with uv installed:

```powershell
uv sync --locked
uv run --locked --offline mypy
uv run --locked --offline pytest -q
```

Python 3.12 is selected by `.python-version`; uv can install it if needed. Setup
may require downloads. Subsequent `uv run --offline` commands use the installed
environment and lockfile. The source store uses the Python standard library,
and the browser API uses Flask.

For the browser workspace, install Node.js 24 and run these commands from the
repository root after `uv sync --locked`:

```powershell
npm.cmd --prefix web ci
npm.cmd --prefix web run build
uv run --offline frag serve --store artifacts/phase01/local-store/browser
```

Open [the local source inspector](http://127.0.0.1:5000). Upload an HTML file,
choose its provenance, and preserve the source. Try `tests/fixtures/synthetic.html`
with the **Synthetic fixture** option. To inspect browser uploads through the CLI,
run `uv run --offline frag inspect --store artifacts/phase01/local-store/browser`.
Click **Refresh** to see sources ingested through the CLI while the page was open.
To get a filing from **SEC EDGAR**, enter a company ticker or SEC CIK, the
calendar year it was filed, and the form (for example, `MSFT`, `2023`, `10-K`).
Click **Find filings**, choose a result by filing date or reporting period, and
click **Download selected filing**. This opens the saved HTML source record with
its hash and SEC provenance. To enable searches and fresh downloads, put the
following line in the Git-ignored `.env` file at the repository root, using your
project name and monitored contact address:

```dotenv
SEC_USER_AGENT="Your Organization contact@your-domain.example"
```

Start the UI with the saved setting:

```powershell
uv run --locked --offline --env-file .env frag serve --store artifacts/phase01/local-store/browser
```

Use the Microsoft FY2023 10-K
shortcut or **Saved sources** to inspect a cached filing offline. Revenue
extraction supports the Microsoft FY2023 layout and the Microsoft FY2022
layout when its accession is supplied. The FY2022 filing's facts are provisional.
[SEC EDGAR submissions API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
Use `--port` to choose another available port. Setup may fetch dependencies.
After updating FRAG, restart `frag serve` and reload the page so the browser
and API use the same version.
Offline review of saved sources uses only localhost.

To repeat the automated browser check with an installed Google Chrome, stop
at the build step above and run:

```powershell
uv run --locked --offline --with playwright python artifacts/phase01/browser-replay.py
```

The check starts its own localhost server, uploads synthetic inputs and the
retained filing to a temporary store, and blocks page requests to other origins.
Omit `--offline` on the first run if uv needs to fetch Playwright.

The following runnable example uses an explicitly labeled **synthetic document**:

```powershell
uv run --offline frag ingest tests/fixtures/synthetic.html --store artifacts/phase01/local-store --provenance synthetic --company "Synthetic Example" --form 10-K
uv run --offline frag inspect --store artifacts/phase01/local-store
```

To inspect just one source using the `source_id` returned by ingest:

```powershell
$source = uv run --offline frag ingest tests/fixtures/synthetic.html --store artifacts/phase01/local-store --provenance synthetic --company "Synthetic Example" --form 10-K | ConvertFrom-Json
uv run --offline frag inspect $source.source_id --store artifacts/phase01/local-store
```

For a locally supplied original HTML document, use the same ingest command with
its disk path and `--provenance local_original`. Optional metadata flags are
`--company`, `--accession`, `--form`, `--filing-date YYYY-MM-DD`, and `--source-url`.
Omitted metadata is JSON `null`. The source record retains the supplied claims
as `supplied_unverified`. The parser checks the Microsoft FY2023 10-K's inline
cover fields and matches the statement's annual headers to inline XBRL
contexts. To extract provisional facts from the Microsoft FY2022 10-K,
supply `--accession 0001564590-22-026876`. Declare synthetic inputs as `synthetic`.

## Download and inspect the Microsoft filing

Set `SEC_USER_AGENT` to your project or organization name and a monitored contact
address before a fresh download. The command requests only the Microsoft FY2023
10-K. It makes up to three attempts for transient failures and honors
`Retry-After` within a ten-second wait limit. The SEC asks scripted clients to
identify themselves, minimize requests, and stay within ten requests per second
across all machines. [SEC access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
[SEC user-agent guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions)

```powershell
$secStore = 'artifacts/phase01/local-store/sec'
uv run --locked --offline --env-file .env frag download --store $secStore
```

Here `--offline` governs uv's dependency setup. On a cache miss, `frag download`
contacts SEC EDGAR. Once there is a cached download, the same command reuses the
saved original and checks its hash without contacting the SEC or requiring the
user agent. The download and inspect commands return the source record as JSON.
If inspection shows an unsupported document or a damaged original, use a new
store for another download and keep the previous store for review.

```powershell
$secStore = 'artifacts/phase01/local-store/sec'
$cached = uv run --locked --offline frag download --store $secStore | ConvertFrom-Json
uv run --locked --offline frag inspect $cached.source_id --store $secStore
```

For a local fallback, set `$filingPath` to the path to your original HTML. Use a
separate store so the original provenance stays intact if both inputs have
identical bytes.

```powershell
$localStore = 'artifacts/phase01/local-store/microsoft-local'
$local = uv run --locked --offline frag ingest $filingPath --store $localStore --provenance local_original | ConvertFrom-Json
uv run --locked --offline frag inspect $local.source_id --store $localStore
```

The live download succeeded with a monitored contact email in the user agent.
The response includes an extra script element and has its own source hash.
Offline inspection passed. [Acquisition run record](artifacts/phase01/SEC_ACQUISITION.md)

## Offline replay and source records

Replay the retained synthetic input or Microsoft HTML with networking
actively forbidden in each ingest and inspection process.

```powershell
uv run --locked --offline python artifacts/phase01/replay.py
uv run --locked --offline python artifacts/phase01/replay.py --microsoft
```

`uv --offline` prevents uv downloads. The replay harness and regression tests
add a Python audit hook that rejects all socket operations in CLI processes.
Both replays use temporary stores and write JSON to stdout. The Microsoft replay
decompresses the preserved original, ingests it twice, checks the catalogue for
one source, and inspects the two saved facts and bytes after removing the input.
For the standalone PowerShell ingest and inspect commands using that same original,
see the [Phase 1 handoff](artifacts/phase01/HANDOFF.md#reproduce).

The store keeps unchanged bytes under `originals/<sha256>.html`, separately from
the source catalogue `sources.sqlite3`. `sha256:<hex>` identifies source bytes.
Inspection checks their hash. Identical bytes and metadata reuse the first record
and its provenance, even from another input path. Conflicting metadata or
provenance returns an error and leaves the first record intact; replay with the
same metadata. Different bytes create a different source. Copy the entire store
for offline inspection elsewhere; `original_path` resolves to the current copy.
Treat the store as trusted local state, and keep backups of original evidence.

Successful commands print JSON to stdout. Operational errors print JSON to stderr
and exit 1; invalid command syntax exits 2. `inspect` without an ID lists all
sources and their count. Each source exposes parser and evidence versions, fact
statuses, extraction diagnostics, and open verification requirements. Amounts are
decimal strings, with JSON `null` for unknown normalized amounts. The parser reads
HTML as data. The locators point to the original HTML using one-based line and
character offsets and physical table, row, and cell ordinals. Column ordinals use
the logical grid after spans are applied. Expand an observation in the browser
to see its bounded applicable notes and source coordinates. Comparison status
and scope caveats appear below the observations. Verification currently covers
the retained Microsoft filing and uses an independently inspected reference
with a recorded source hash.

## Calculate verified revenue growth

In the browser, select the preserved filing, enter the prior and current fiscal
years, and choose **Calculate revenue growth**. The result includes a trace and
links that open the original cells and disclosures as text in new tabs.

From PowerShell, after ingesting a filing as shown above:

```powershell
.venv/Scripts/frag.exe growth $local.source_id 2022 2023 --store $localStore
```

The same calculator serves both entry points. The CLI emits JSON with typed
percent, operand roles, citations, and comparison caveats. An evidence issue
returns `status: "unavailable"` with the reason and any available observations.
A verified zero baseline returns `status: "undefined_zero_baseline"` with a
labeled absolute change. [Calculator validation and replay](artifacts/phase02/GROWTH_HANDOFF.md)

## Ask the filing for annual revenue

In the browser, open a preserved filing and use **Ask the filing**. Each
question is independent. Supported examples include “What was reported
consolidated revenue in FY2023?”, “Revenue for fiscal year 2023”, and
“What was FY2022 revenue?”. Specify one fiscal year. The answer uses a
verified observation in the selected filing and links to the original cell.

For reported consolidated revenue growth, provide both fiscal years in
chronological order. Try “How did revenue change from FY2022 to FY2023?”,
“Revenue growth from fiscal year 2022 to fiscal year 2023”, or “What was
revenue growth between FY2022 and FY2023?”. The answer includes the
percentage, calculation steps, and evidence from the original filing.

Run the explicit setup from the repository root in Windows PowerShell. It
downloads the pinned Windows x64 CPU build and Q4_K_M weights on cache miss,
checks both SHA-256 digests, and unpacks the runtime into `.frag-model`.

```powershell
.\scripts\setup-local-model.ps1
```

Start the planner in its own PowerShell window from the repository root.
It loads the saved weights in offline mode and listens on loopback.

```powershell
.\scripts\start-local-model.ps1
```

Use the browser workspace or ask from PowerShell after ingesting the local
filing shown above. The CLI reads the question at its prompt, which keeps
the text out of shell command history. Enter `What was revenue in FY2023?`
when prompted. The application saves a run only when you pass `--record`.

```powershell
.venv/Scripts/frag.exe ask $local.source_id --store $localStore
.venv/Scripts/frag.exe ask $local.source_id --store $localStore --record .frag-model/my-lookup.json
```

The `--record` option requires a new path and saves the full validation run.
Stop the planner with Ctrl+C in its PowerShell window, then replay against
the same store.

```powershell
.venv/Scripts/frag.exe replay-lookup .frag-model/my-lookup.json --store $localStore
```

[Model and runtime pins, measurements, and retained validation runs](artifacts/phase02/LOOKUP_HANDOFF.md)

To record and replay a growth answer using the same filing store, ask while
the planner is running, then stop the planner before running replay.

```powershell
.venv/Scripts/frag.exe ask $local.source_id 'How did revenue change from FY2022 to FY2023?' --store $localStore --record .frag-model/my-growth.json
.venv/Scripts/frag.exe replay-ask .frag-model/my-growth.json --store $localStore
```

[Growth chat validation and measurements](artifacts/phase02/CHAT_GROWTH_HANDOFF.md)

Importable entry points are `frag.store.SourceStore`, `SourceMetadata`, and
`SourceError`. Use `SourceStore(Path(...)).ingest(...)` and `.inspect(...)` with
the same metadata and provenance semantics as the CLI.

See the [Phase 1 handoff](artifacts/phase01/HANDOFF.md) and
[project status](docs/PROJECT_STATUS.md) for acceptance evidence and limitations.

## Annual revenue across preserved filings

Use **Ask the collection** on the browser home screen or `ask-collection`
in PowerShell. Name one company and one fiscal year. The workspace can open
the exact revenue cell from cached filing HTML without a model or network.

Build the reproducible collection and keep its store and validation records.

```powershell
$collectionRun = Join-Path 'build' ([guid]::NewGuid().ToString())
uv run --locked --offline python artifacts/phase03/collection-replay.py --work-dir $collectionRun
$collectionStore = Join-Path $collectionRun 'store'
$collectionRecord = Join-Path $collectionRun 'manual-lookup.json'
.venv/Scripts/frag.exe index-collection --store $collectionStore
.venv/Scripts/frag.exe ask-collection "What was Microsoft's revenue in FY2023?" --store $collectionStore --record $collectionRecord
.venv/Scripts/frag.exe replay-collection $collectionRecord --store $collectionStore
```

The same question entry point accepts reported consolidated revenue growth.

```powershell
.venv/Scripts/frag.exe ask-collection "What was Microsoft's reported consolidated revenue growth from FY2022 to FY2023?" --store $collectionStore
.venv/Scripts/python.exe artifacts/phase03/collection-replay.py --growth
```

See the [one-pass growth baseline](artifacts/phase03/GROWTH_BASELINE.md) for
the retained offline runs and context limit.

Select **Bounded recovery** in the browser or pass `--mode bounded` in
PowerShell to search the same snapshot for a fiscal year omitted from the
first pass. The CLI accepts `--max-calls` and `--max-seconds`. Use the
offline harness to save and replay the same question in both modes.

```powershell
$recoveryRun = Join-Path 'build' ([guid]::NewGuid().ToString())
.venv/Scripts/python.exe artifacts/phase03/collection-replay.py --bounded --work-dir $recoveryRun
.venv/Scripts/frag.exe replay-collection (Join-Path $recoveryRun 'recovery-recovered.json') --store (Join-Path $recoveryRun 'store')
```

[Bounded recovery cases and budget behavior](artifacts/phase03/BOUNDED_RECOVERY.md)

To reproduce the paired Phase 3 comparison on Windows, make sure
`nvidia-smi` is on PATH and run the harness with a new output directory.
It uses the preserved corpus, records both modes for each question, and
reopens the cited evidence offline.

```powershell
.venv/Scripts/python.exe artifacts/phase03/collection-replay.py --paired --work-dir .venv/phase03-paired
```

[Phase 3 handoff and measured results](artifacts/phase03/HANDOFF.md)

Omit the question argument to enter it at the prompt. The application creates
a validation record only when you pass `--record`.
[Corpus, expected results, and browser smoke commands](artifacts/phase03/COLLECTION_HANDOFF.md)

## FinQA annotated-evidence diagnostic

Replay the saved dev outcomes without starting the planner or downloading
FinQA. The command prints the number of replayed questions and the internal
result summary.

```powershell
.venv/Scripts/python.exe -m frag.finqa replay artifacts/phase04/finqa-dev-run.json
```

[PowerShell commands for pinned input acquisition and a fresh dev run](artifacts/phase04/FINQA_DIAGNOSTIC.md)

Use the [offline scoring parity commands](artifacts/phase04/FINQA_DIAGNOSTIC.md#offline-scoring-parity)
to check execution and program matches against the pinned FinQA evaluator
and account for every question in the saved dev cohort.

## FinQA evidence comparison

The paired dev evaluation compares annotated excerpts with keyword retrieval
on the same questions. The [Windows run and offline replay instructions](artifacts/phase04/FINQA_COMPARISON.md)
include the measured results and the protocol frozen for public test.

## FinQA public test

Run or resume the same pinned public test cohort in both evidence modes.
Use the [pinned input and runtime setup](artifacts/phase04/FINQA_PUBLIC_TEST.md#run-resume-and-inspect-on-windows).
Run these commands from the repository root in Windows PowerShell.

```powershell
$env:TEMP = (Resolve-Path build).Path
$env:TMP = $env:TEMP
$cache = 'build/finqa'
$checkpoint = Join-Path $cache 'public-test.sqlite'
$report = 'artifacts/phase04/finqa-public-test-report.json.gz'
build/finqa-venv/Scripts/python.exe -m frag.finqa_test run $cache $checkpoint
build/finqa-venv/Scripts/python.exe -m frag.finqa_test status $cache $checkpoint
build/finqa-venv/Scripts/python.exe -m frag.finqa_test score $cache $checkpoint $report
build/finqa-venv/Scripts/python.exe -m frag.finqa_test replay $cache $report
```

Use the same checkpoint to resume. The status command can also run in a
second window during inference.

## SEC held-out acceptance

The SEC checkpoint reports accuracy, citation support, grounded abstention,
and task completion across 18 reserved cases. The checkpoint gives the
PowerShell commands to prepare the frozen snapshot and copy the runner archive
from custody. [SEC held-out acceptance checkpoint](artifacts/phase04/SEC_ACCEPTANCE.md)

After preparing that snapshot in PowerShell, verify the saved cases offline.

```powershell
.venv/Scripts/python.exe "$snapshot/artifacts/phase04/sec_holdout_runner.py" replay "$snapshot/recorded/freeze.json" --inputs "$snapshot/inputs.zip" --work "$snapshot/replay" --saved-run "$snapshot/recorded/live/report.json"
```

The command prints `{"matched": 18}`. Run the scorer commands in the custody
environment to verify the recorded metrics.

## Phase 5 SEC scorer controls

From the repository root in PowerShell, replay the 15 saved development
questions offline and audit the answers against the original filings.

```powershell
$replay = "build/issue33-positive-$([guid]::NewGuid())"
& artifacts/phase05/acceptance-replay.ps1 -Destination $replay
if ($LASTEXITCODE -ne 0) { throw 'Offline replay failed.' }
.venv/Scripts/python.exe artifacts/phase05/acceptance_score.py . "$replay/live.json" "$replay/replay/report.json" "$replay/acceptance-score.json"
if ($LASTEXITCODE -ne 1) { throw 'Expected the existing Microsoft citation failure.' }
```

Replay reports 30 matches. The scorer exits with code 1 for the known
Microsoft currency citation gap and writes the per-case findings to JSON.
The negative controls alter a saved answer and a citation to verify that
replay detects both mismatches. [Scorer and offline replay controls](artifacts/phase05/ACCEPTANCE_SCORER.md)
