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
