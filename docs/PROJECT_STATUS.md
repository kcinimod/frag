# Project status

Phase 1 preserves original source bytes and exposes verified FY2022 and
FY2023 reported consolidated revenue from Microsoft's FY2023 10-K (accession
`0000950170-23-035122`). The CLI and localhost browser use the same store and
parser. The retained HTML and source manifest support offline replay. See the
[revenue verification handoff](../artifacts/phase01/VERIFICATION_HANDOFF.md).

- Issue #2 delivered local source preservation, integrity checks, and repeatable
  ingest and inspection. Issue #7 added local browser upload and inspection.
- Issue #3 adds statement extraction, source and inline XBRL locators, explicit
  unknown amounts, and diagnostics for unsupported or ambiguous geometry.
- Issue #4 verifies each observation against independently inspected source
  evidence, retains applicable notes and scope caveats, and reports comparison
  compatibility separately. The retained copy came from an EDGAR mirror.
- Issue #5 adds direct SEC acquisition and offline cache reuse to the CLI.
  Controlled responses and local replay passed. A live request returned HTTP
  403, so the direct byte comparison remains outstanding.
  [Acquisition run record](../artifacts/phase01/SEC_ACQUISITION.md)
- The wider Phase 1 handoff remains open.
