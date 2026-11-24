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
- Issue #11 adds filing chatbot questions for growth between two fiscal years.
  The local model returned a valid plan for Microsoft FY2022 to FY2023, and
  the deterministic calculator returned 6.88% with its trace and citations.
  [Growth chat handoff](../artifacts/phase02/CHAT_GROWTH_HANDOFF.md)
- Issue #13 adds collection-wide annual revenue lookup in the CLI and browser.
  The offline corpus reproduced Microsoft FY2022 and FY2023 revenue and
  Chrome opened both original cells.
  [Collection handoff](../artifacts/phase03/COLLECTION_HANDOFF.md)
- Issue #14 adds one-pass revenue growth across the collection. The offline
  baseline reproduced 6.88% for Microsoft FY2022 to FY2023 and retained
  partial, incompatible, and zero-baseline runs.
  [Growth baseline](../artifacts/phase03/GROWTH_BASELINE.md)
- Issue #15 adds bounded fiscal-year recovery. A controlled first pass
  omitted FY2022, and bounded retrieval recovered it and replayed the
  6.88% answer offline with the original citations.
  [Bounded recovery](../artifacts/phase03/BOUNDED_RECOVERY.md)
- Issue #16 adds bounded recovery of original statement and disclosure context.
  The paired Phase 3 comparison replayed 11 cases in both modes, with offline
  citation validation and Windows resource measurements.
  [Phase 3 handoff](../artifacts/phase03/HANDOFF.md)
- Issue #12 completes Phase 3. Partial growth results retain the statement and
  applicable notes for the verified year. Offline Chrome opened Note 8 from
  the Microsoft FY2023 partial result and the 6.88% growth answer. Bounded
  retrieval can also recover a verified pair when first-pass observations
  come from different filings.
  [Phase 3 handoff](../artifacts/phase03/HANDOFF.md)
- Issue #18 runs the FinQA annotated-evidence diagnostic on 13 official dev
  questions. The run retains the split audit, delivered planner inputs,
  attempted plans, and deterministic outcomes for offline replay.
  [FinQA dev diagnostic](../artifacts/phase04/FINQA_DIAGNOSTIC.md)
- Issue #19 replayed and scored all 13 dev cases with the pinned upstream
  evaluator. Execution and program matches were both 2/13, including ten
  invalid plans in the denominator.
  [FinQA score report](../artifacts/phase04/finqa-dev-score.json)
- Issue #20 compares both FinQA evidence modes on the same 13 dev questions,
  records ranking and context losses, measures the local Windows runtime,
  and freezes the settings for the public test evaluation.
  [FinQA evidence comparison](../artifacts/phase04/FINQA_COMPARISON.md)
- Issue #21 completed and replayed the frozen FinQA public test comparison,
  with 1,147 outcomes per mode. Internal execution matched 30 answers for
  the annotated-evidence diagnostic and 14 for retrieved evidence.
  Scorer parity remains unresolved in both modes.
  [FinQA public test results](../artifacts/phase04/FINQA_PUBLIC_TEST.md)
- Issue #22 verifies annual revenue lookup on the Microsoft and Apple
  development 10-Ks. The filing workspace opens Apple's original statement
  cells and applicable disclosures offline.
  [Development evidence and replay](../artifacts/phase04/development/README.md)
- Issue #23 verifies FY2022 to FY2023 growth on both development 10-Ks.
  Apple returns −2.80% with fiscal-calendar and currency caveats. Growth questions
  expose evidence gaps and keep supported observations available for
  inspection. [Development growth and replay](../artifacts/phase04/development/README.md#fy2022-to-fy2023-growth)
- Issue #24 reserves 18 cases from six domestic 10-K issuer families. The
  offline audit verified the original hashes, case coverage, and scoring
  evidence. [Holdout handoff](../artifacts/phase04/SEC_HOLDOUT.md)

- Issue #25 evaluated all 18 SEC holdout cases and matched all 18 in offline
  replay. The workflow answered 0/12 answerable cases. The frozen rubric
  credited 4/6 abstentions and 4/18 tasks. Review found a contradicted
  missing-year claim in all four credited cases.
  [SEC held-out acceptance checkpoint](../artifacts/phase04/SEC_ACCEPTANCE.md)

- Issue #27 froze 15 SEC development questions across six issuer families.
  The pre-change run produced 4/13 correct numeric answers, 3/15 end-to-end
  completions, and 30/30 cold and warm offline replay matches.
  [Phase 5 development baseline](../artifacts/phase05/README.md)

- Issue #28 verifies annual revenue lookups from the original Amazon,
  Alphabet, and Walmart statements. On the fixed development questions,
  17/22 requested observations matched the original locator, 16/22 verified,
  and 30/30 results and citations matched in offline replay.
  [Unseen-issuer lookup checkpoint](../artifacts/phase05/UNSEEN_LOOKUP.md)

- Issue #29 verifies Intel annual revenue from the original statement, fiscal
  calendar, and recognition disclosures. Six filing and collection lookups
  passed with original citations, and all 30 cold and warm results replayed.
  [Development layout verification](../artifacts/phase05/DEVELOPMENT_LAYOUTS.md)
