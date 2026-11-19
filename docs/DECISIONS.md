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
