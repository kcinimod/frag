# FRAG

Local, evidence-first SEC financial QA work in progress. The CLI and local
browser workspace preserve and inspect sources. Revenue extraction and
verification are later Phase 1 slices.

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
uv run --locked --with playwright python artifacts/phase01/browser-replay.py
```

The check starts its own localhost server, uses a temporary store and synthetic
inputs, and blocks page requests to other origins. uv may fetch Playwright on
the first run.

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
Omitted metadata is JSON `null`. These are supplied claims, recorded as
`supplied_unverified`; no identity is inferred from filenames or content.
Declare synthetic inputs as `synthetic`. This command does not authenticate a
document, and neither provenance choice establishes real-source acceptance.
No original filing was available for the recorded run.

Replay with networking actively forbidden, including new ingest and inspection
processes, using the retained synthetic input:

```powershell
uv run --offline python artifacts/phase01/replay.py
```

`uv --offline` prevents uv downloads. The replay harness and regression tests
add a Python audit hook that rejects all socket operations in CLI processes.
The application has no download or inference functionality.

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
sources and their count. Each source exposes an empty `facts` list, null
`parser_version`, `source_preserved` status, and outstanding requirements.
Inputs are preserved as opaque bytes without parsing or executing HTML; the
caller is responsible for supplying HTML. Synthetic inputs and successful
hash checks are insufficient for financial evidence verification.

Importable entry points are `frag.store.SourceStore`, `SourceMetadata`, and
`SourceError`. Use `SourceStore(Path(...)).ingest(...)` and `.inspect(...)` with
the same metadata and provenance semantics as the CLI.

See [project status](docs/PROJECT_STATUS.md) and the
[checkpoint handoff](artifacts/phase01/HANDOFF.md) for evidence and remaining work.
