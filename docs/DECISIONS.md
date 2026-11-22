# Decision log

## Issue #2: immutable local source preservation

The source identifier is `sha256:<hash of unchanged input bytes>`. Original bytes
live in a separate directory from a SQLite source catalogue. SQLite serializes
writes and enforces a unique source identifier. Metadata and declared provenance
are immutable: conflicting retries fail rather than silently relabeling evidence.
The first input path and UTC preservation timestamp remain available on retries.
Unknown identity fields and parser version are null; no parser runs in this ticket.

The public CLI ingest-and-inspect workflow is the already confirmed testing
boundary in issue #1. Tests use temporary stores and fresh CLI processes whose
socket operations are denied. Synthetic fixtures cannot establish real-source
or financial-verification acceptance. Content is opaque bytes, never instructions.

This log records implementation choices within issue #2. Downloads, extraction,
financial verification, and their consequential design decisions remain pending.

## Phase 1 design discussion: feature and UI together

The project owner agreed that each future feature issue should include a
reviewable UI outcome in one evolving app. The first UI follow-up will cover the
already completed issue #2, which remains closed. It will show the preserved
source ID, hash, supplied filing metadata, and provenance, including whether the
input is synthetic. The project owner also confirmed that this first slice will
support browser-based ingestion of local HTML. Issue #3 will extend that same
source view with provisional revenue facts, their supporting evidence, and
unresolved requirements.

The project owner confirmed the direction of an interactive evidence workspace.
Use a TypeScript frontend so later slices can add side-by-side comparisons,
linked evidence, and filters. The stack is React with Vite for the
frontend and a small Flask API backed by the same Python ingestion and inspection
logic and store as the CLI. Build the browser assets with Node and serve them
from the Python app on localhost through uv for offline review. Docker is
deferred for this slice.
In the browser, the user will select a local HTML file, declare its provenance,
and optionally supply filing metadata. A successful upload opens the saved
source record. Repeating an identical submission returns the same record.
Conflicting metadata or provenance displays an error and preserves the record.

The browser acceptance checks cover offline upload and inspection, repeat
submissions, conflicting claims, and shared storage with the CLI. The local
Phase 1 specification now includes the browser workflow. The first UI follow-up
is tracked in [issue #7](https://github.com/kcinimod/frag/issues/7).

## Issue #3 provisional annual revenue

The parser selects the statement heading and Total revenue label, associates
the displayed years with values through the logical table grid, and checks the
inline XBRL annual contexts for the original layout. The original document's
inline cover fields identify the supported form, entity, and report end without
requiring supplied metadata. Currency comes from the
statement's USD declaration or referenced XBRL unit. The statement scale applies
to revenue even when the disclosure also has a per-share exception. Amounts use
exact decimal strings. An unresolved amount stays null and ambiguous geometry
produces a diagnostic.

The source record keeps its byte-derived identity. The fact ID derives from
source ID, metric, and fiscal year. The SQLite catalogue stores extraction
results by source ID and parser version separately from the original source
record. Reingestion fills the current parser version while preserving earlier
results. Inspect can derive the current view in memory for older stores.

## Issue #4 independent verification

The independent reference is packaged separately from the extractor. For the
one reviewed filing, it pins the preserved source identity and fingerprints of
manually selected statement elements, contexts, note headings, and disclosure
ranges. A verified fact requires matching fields and geometry, resolvable original
markup, and bounded applicable notes. Comparison additionally requires both
observations and the reviewed comparative disclosures. The original input hash
is required for real-source acceptance. Explicitly synthetic derivatives report
per-observation reference matches while retaining provisional fact status.

The catalogue cache key combines parser and evidence versions. Observation IDs
remain byte-, metric-, and period-based. A failed per-observation annual context
leaves the other period available. Ambiguous shared statement geometry still
produces a source-level diagnostic.

## Issue #5 SEC acquisition

The download command targets the selected EDGAR document and checks the source
catalogue for a preserved SEC response before validating the user-agent
setting or opening a connection. The original bytes and catalogue record are the cache. A local
input can cite the same filing URL while retaining its local provenance, so the
download lookup uses both the URL and the `sec_download` provenance. Use
separate stores when comparing direct and locally supplied bytes to preserve
the storage contract for immutable provenance.

Requests use an operator-configured identifying user agent. Retry delays start
at one second for transient errors and respect a longer `Retry-After` within
the wait limit. A server-requested wait beyond the limit ends the command so
the next request can be scheduled separately. The workstation's direct SEC
request initially returned HTTP 403. A monitored contact succeeded on a later
attempt. [SEC acquisition record](../artifacts/phase01/SEC_ACQUISITION.md)

## Issue #6 Phase 1 acceptance evidence

The checked-in, independently reviewed mirror copy is the replay input. Its
size matches the SEC filing index and its preserved source hash pins both
verified observations. The separate direct response retains its own source hash
and provisional status. The Phase 1 manifest points to the original archive,
derived facts, and independent reference. Both replay modes use temporary
stores and emit JSON to stdout so a synthetic run cannot replace that manifest.
The replay blocks Python socket operations in each CLI process. The Phase 1
handoff marks the review checkpoint. [Phase 1 handoff](../artifacts/phase01/HANDOFF.md)

## Local planner for annual revenue lookup

Use llama.cpp b6500 and Qwen2.5-0.5B-Instruct Q4_K_M on the CPU for issue #10.
Setup verifies the runtime archive and weights against pinned SHA-256
digests. The application sends one schema-constrained request over loopback
and validates the proposed fact ID against the independently resolved fiscal
year and the selected filing's verified evidence. The model uses structured
fact fields as context. The citation viewer renders the original cell.
The process can run with the model loaded for repeated local questions.
[Lookup acceptance and measurements](../artifacts/phase02/LOOKUP_HANDOFF.md)

## Filing chatbot for reported revenue growth

Resolve the requested operation and chronological fiscal-year roles before
calling the planner. The plan must match the three-step program for the
selected filing's eligible facts. The existing calculator checks comparison
compatibility before arithmetic and returns the trace and original filing
citations for both the calculator and the chatbot. Saved chatbot plans use
`replay-ask`. The earlier `replay-lookup` command is an alias.
[Growth chat acceptance](../artifacts/phase02/CHAT_GROWTH_HANDOFF.md)

## Collection revenue lookup

Build a content-addressed collection snapshot from a single catalogue read
view using versioned extraction results. Keep the verified evidence and
distinct observations linked to their original sources and parent tables.
Resolve company, operation, and reporting period before keyword ranking and
structured selection. Pin explicit replay to the exact recorded source set
and validate its versions, candidate ranking, and outcome.
[Collection handoff](../artifacts/phase03/COLLECTION_HANDOFF.md)

## One-pass collection revenue growth

Apply the context limit to revenue observations and separately selected
comparison records and disclosures. Require a verified comparative and
current pair from one filing and route that pair through the deterministic
calculator. Keep selected verified observations and open requirements when
coverage is incomplete. Include comparison evidence in the snapshot hash
so replay detects changes to the basis and disclosures.
[Growth baseline](../artifacts/phase03/GROWTH_BASELINE.md)

## Bounded fiscal-year recovery

Use the same first-pass selection in both retrieval modes. When one year is
missing, filter already-ranked eligible candidates for that year within the
pinned snapshot. Prefer evidence from the initially selected filings so the
existing calculator can check the comparison on its original basis.

Count searches and calculations against the call budget. Check elapsed
time before and after each action and discard results that arrive past the
limit. Reuse the recorded elapsed checkpoints on offline replay so machine
speed cannot change the replayed stop reason.
[Bounded recovery validation](../artifacts/phase03/BOUNDED_RECOVERY.md)

## Bounded filing context recovery

Use a shared final context limit and allow explicit replay to constrain what
the first pass sees. Bounded retrieval follows table and disclosure references
from eligible observations in the pinned snapshot. It checks the locators
against the preserved original and counts each follow-up against the existing
budget. The calculator uses the facts and comparison evidence selected for the
answer. Keep the earlier retrieval versions replayable so the original
validation records remain reproducible.
[Phase 3 handoff](../artifacts/phase03/HANDOFF.md)
