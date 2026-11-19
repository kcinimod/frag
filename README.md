# FRAG

Local, evidence-first SEC financial QA work in progress. The CLI and browser
workspace preserve original source bytes and expose provisional consolidated
revenue for FY2022 and FY2023 from the selected Microsoft FY2023 10-K.

From the repository root in Windows PowerShell, with uv installed:

```powershell
uv sync --locked
uv run --offline mypy
uv run --offline pytest
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
Use `--port` to choose another available port. Setup may fetch dependencies.
Once built and installed, the app uses only localhost during review.

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
as `supplied_unverified`. The parser recognizes the selected Microsoft FY2023
10-K from its inline cover fields and checks the statement's annual headers
against inline XBRL contexts. Declare synthetic inputs as `synthetic`.

Replay the retained synthetic input or Microsoft HTML with networking
actively forbidden in each ingest and inspection process.

```powershell
uv run --offline python artifacts/phase01/replay.py
uv run --locked --offline python artifacts/phase01/replay.py --microsoft
```

`uv --offline` prevents uv downloads. The replay harness and regression tests
add a Python audit hook that rejects all socket operations in CLI processes.
The Microsoft replay decompresses a retained snapshot into a temporary input,
then ingests it twice and inspects the saved facts after removing that input.

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
sources and their count. Each source exposes the parser version, any provisional
facts, extraction diagnostics, and open verification requirements. Amounts are
decimal strings, with JSON `null` for unknown normalized amounts. The parser reads
HTML as data. The locators point to the original HTML using one-based line and
character offsets and physical table, row, and cell ordinals. Column ordinals use
the logical grid after spans are applied. Expand a provisional observation in
the browser to see these coordinates.

Importable entry points are `frag.store.SourceStore`, `SourceMetadata`, and
`SourceError`. Use `SourceStore(Path(...)).ingest(...)` and `.inspect(...)` with
the same metadata and provenance semantics as the CLI.

See [project status](docs/PROJECT_STATUS.md) and the
[revenue extraction handoff](artifacts/phase01/REVENUE_HANDOFF.md) for evidence
and remaining work.
