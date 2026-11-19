# FRAG

Local, evidence-first SEC financial QA work in progress. Issue #2 provides an
importable Python package and a JSON CLI for **preservation and inspection only**.
It does not extract revenue, verify filing identity, or produce verified facts.

From the repository root in Windows PowerShell, with uv installed:

```powershell
uv sync --locked
uv run --offline mypy
uv run --offline pytest
```

Python 3.12 is selected by `.python-version`; uv can install it if needed. Setup
may require downloads. Subsequent `uv run --offline` commands use the installed
environment and lockfile. Production code uses only the Python standard library.

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
