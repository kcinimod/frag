# Project status

Issue #2 implements local source preservation and inspection. Phase 1 remains
incomplete. No original Microsoft filing has been acquired, and no revenue has
been extracted or verified.

- Implemented: importable Python package, uv lockfile, ingest/inspect JSON CLI,
  original-byte preservation, source metadata with explicit unknowns, stable
  identifiers, duplicate-free replay, and conflict/integrity diagnostics.
- Evidence: [checkpoint handoff](../artifacts/phase01/HANDOFF.md),
  [synthetic source manifest](../artifacts/phase01/source-manifest.json),
  and validation output under `artifacts/phase01/`.
- Next milestone: acquire or supply the original selected Microsoft FY2023 10-K,
  then implement the separately scoped extraction and verification tickets.
- The local browser workspace ([#7](https://github.com/kcinimod/frag/issues/7))
  supports HTML upload, browsing, and source
  inspection using the same store as the CLI. The Windows build and type checks
  passed, along with 19 Python tests and the Chrome replay using synthetic
  inputs and blocked external page requests. See the README to reproduce.
- Acquisition, inference, calculation, and retrieval remain outside this slice.

The financial acceptance checklist remains unchecked because its items combine
source preservation with facts, contexts, or verification outside this ticket.
