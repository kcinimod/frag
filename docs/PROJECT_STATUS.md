# Project status

Phase 1 acceptance checks passed for the retained original Microsoft FY2023
10-K (accession `0000950170-23-035122`). FY2022 and FY2023 reported consolidated
revenue are independently verified and compatible on their reported basis.
Reingestion kept one source and two stable fact IDs. Socket-blocked replay
inspected the saved bytes and facts after removing the input. Issue #6
delivered the acceptance evidence for Phase 1. The project owner reviewed the
Phase 2 calculator and its offline results.
[Phase 1 handoff](../artifacts/phase01/HANDOFF.md)

- Issue #2 delivered local source preservation, integrity checks, and repeatable
  ingest and inspection. Issue #7 added local browser upload and inspection.
- Issue #3 adds statement extraction, source and inline XBRL locators, explicit
  unknown amounts, and diagnostics for unsupported or ambiguous geometry.
- Issue #4 verifies each observation against independently inspected source
  evidence, retains applicable notes and scope caveats, and reports comparison
  compatibility separately. The retained copy came from an EDGAR mirror.
- Issue #5 adds direct SEC acquisition and offline cache reuse to the CLI.
  A live request with a monitored contact succeeded, and cache reuse and
  inspection passed offline. The SEC response adds one 105-byte script
  element to the verified mirror copy. The direct response's observations
  are provisional under its own source hash.
  [Acquisition run record](../artifacts/phase01/SEC_ACQUISITION.md)
- The browser workspace searches EDGAR by company ticker or CIK, filing year,
  and form. It preserves the selected HTML through the same download cache.
- Issue #9 delivers verified revenue growth through the CLI and browser.
  Both replayed the retained Microsoft filing offline and returned 6.88%.
  The project owner reviewed the calculator and its offline results.
  [Calculator handoff](../artifacts/phase02/GROWTH_HANDOFF.md)
  [Owner review](https://github.com/kcinimod/frag/issues/9#issuecomment-7061708387)
- Issue #10 adds annual revenue lookup through the local planner. The actual
  CPU model answered both retained fiscal years offline. Explicit validation
  runs replayed with the model stopped.
  [Lookup handoff](../artifacts/phase02/LOOKUP_HANDOFF.md)
