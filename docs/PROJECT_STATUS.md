# Project status

Issues #62 and #63 extend standalone rules-only extraction. On the opened
cohorts it matches all 21 #54 observations and all 12 #59 observations.
All exact observations remain provisional. Fresh issuer-disjoint evaluation
is pending. [Development replay](../artifacts/phase06/REVENUE_EXTRACTION_FOLLOWUPS.md)

Issue #60 completed the issuer-disjoint extraction comparison. Rules alone
and the shortlisted model matched 9 of 12 reviewed observations. The
model-only strategy matched zero. Neither model met the adoption gate.
[Held-out results and replay](../artifacts/phase06/REVENUE_SELECTION_ACCEPTANCE.md)

Issue #58 compared all three revenue selectors on the seven opened #54
filings and two synthetic controls. Rules alone and the shortlisted model
each selected all seven reviewed rows and matched 12 of 21 observations.
The model-only strategy selected two reviewed rows and matched zero
observations. Offline replay reproduced all nine cases.
[Paired results and replay commands](../artifacts/phase06/REVENUE_SELECTION_COMPARISON.md)

Issue #56 established the rules-alone baseline for the #55 selection
experiment. It selected the reviewed consolidated revenue row on all seven
opened #54 filings and matched 12 of 21 reviewed annual observations exactly.
The result records three extraction gaps and four verification gaps.
[Baseline and replay commands](../artifacts/phase06/REVENUE_SELECTION_BASELINE.md)

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

- Issue #30 calculates reported revenue growth for Amazon, Alphabet, Walmart,
  and Intel from compatible verified observations. Intel returns −14.00% and
  explains its 53-week and 52-week periods. An equal-length request withholds
  the percentage and retains both cited amounts. The fixed development run
  recorded 12/13 correct numeric answers and 30/30 offline replay matches.
  [Verified growth checkpoint](../artifacts/phase05/VERIFIED_GROWTH.md)

- Issue #31 distinguishes absent statement periods from extraction and
  verification gaps in filing-scoped lookup and growth. The CLI and Chrome
  checked Apple and Microsoft examples against the preserved originals and
  reopened the verified companion amounts and their disclosures. All 30
  cold and warm development outcomes and citations matched in offline replay.
  [Evidence gap checkpoint](../artifacts/phase05/EVIDENCE_GAPS.md)

- Issue #32 sealed 15 fresh SEC holdout cases from six issuer families.
  The offline audit checked seven original 10-Ks, four statement layouts,
  19 corroborated annual observations, and zero issuer overlap with either
  prior cohort. The separate runner and scorer archives are in local custody.
  [Phase 5 holdout handoff](../artifacts/phase05/SEC_HOLDOUT.md)

- Issue #33 validated the stricter scorer on the 15 development questions.
  All 30 saved results and citations reproduced offline. Altering one saved
  result and one saved excerpt produced exactly two replay mismatches. The
  scorer rejected the contradicted missing-year control and the existing
  Microsoft growth citation gap. The cold and warm passes each completed
  13 of 15 cases.
  [Scorer and offline replay controls](../artifacts/phase05/ACCEPTANCE_SCORER.md)

- Issue #34 measured the fresh SEC holdout. Each pass produced 0/12
  supported numeric answers and 1/3 grounded abstentions, below the frozen
  thresholds of 11 and 3. All 30 results and citation sets matched offline.
  Statement extraction blocked all answerable cases before the planner.
  [Phase 5 SEC acceptance checkpoint](../artifacts/phase05/SEC_ACCEPTANCE.md)

- Issue #36 froze and measured the pre-change Phase 6 workflow on the 15
  opened cases and 15 earlier regressions. Both cold and warm runs matched
  all 60 results and citation sets offline. The opened cohort had 0/19
  extraction matches, 0/12 supported answers, and 1/3 grounded abstentions
  per pass. The earlier cohort retained 11/13 supported answers and 2/2
  grounded abstentions per pass.
  [Phase 6 baseline](../artifacts/phase06/README.md)

- Issue #37 adds verified Cisco FY2022–FY2024 observations from the preserved
  FY2024 filing. The reviewed FY2024 lookup returns USD 53,803 million and
  the FY2023 to FY2024 calculation returns −5.61%. Socket-blocked regression
  tests reopen the original statement cells, units, and applicable notes.
  [Cisco implementation issue](https://github.com/kcinimod/frag/issues/37)

- Issue #38 verifies six annual revenue observations from the preserved
  P&G and Coca-Cola FY2024 10-Ks. Both FY2024 lookups and FY2023 to FY2024
  growth calculations reproduced with original citations offline.
  [Issue #38 evidence and checks](../artifacts/phase06/PG_KO_REVENUE.md)

- Issue #39 matches ten reviewed observations across four preserved GE,
  Home Depot, and UPS filings. The nine current observations verify, and
  the historical GE observation remains provisional. Six numeric answers,
  two evidence gaps, and 42 opened citation responses reproduced offline.
  [Issue #39 evidence and checks](../artifacts/phase06/GE_HD_UPS_REVENUE.md)

- Issue #40 verifies Coca-Cola's absent-year citation and companion amount,
  adds P&G fiscal-calendar evidence, and restores Microsoft's original USD
  measure in both growth citations. Historical GE remains provisional and
  the Apple FY2024 regression remains incomplete. Five results and 19
  citation responses matched offline and in the browser.
  [Issue #40 evidence and checks](../artifacts/phase06/GROUNDED_EVIDENCE.md)

- Issue #41 classifies both retained Cisco diagnostics as incomplete and
  recognizes a verified, cited companion on incomplete growth. Scorer controls
  confirm that wrong amounts, unsupported citations and operands, contradicted
  reasons, and replay mismatches still block acceptance.
  [Phase 6 scoring controls](../artifacts/phase06/README.md#phase-6-scoring-controls)

- Issue #46 resolves all seven growth questions that stopped at request
  resolution in #44. The filing workflow uses the existing growth operation
  for “as reported” and carries an explicit equal-length requirement into
  the comparison. Regression coverage includes a cited Microsoft calculation,
  a cited P&G fiscal-calendar gap, and clarification before planning.
  [Request resolution ticket](https://github.com/kcinimod/frag/issues/46)

- Issue #42 passes the development gate. The opened cohort matches all 19
  reviewed observations, verifies 18, and completes 15/15 cases in both
  passes. The earlier cohort completes 14/15, with the Apple FY2024 case
  stopping at verification. Both cohorts reproduce all results and citations
  offline. The collection and filing browser checks pass.
  [Development gate results and replay](../artifacts/phase06/DEVELOPMENT_GATE.md)

- Issue #43 seals the independently reviewed fresh SEC holdout. The runner
  and scorer archives are in separate custody outside the checkout. The
  public receipt records both SHA-256 seals.
  [Fresh holdout custody](../artifacts/phase06/SEC_HOLDOUT.md)

- Issue #44 freezes and evaluates the fresh holdout. Both passes fail the
  acceptance gate with 0/12 supported answers and 0/3 grounded abstentions.
  The workflow extracts 3/21 reviewed observations and verifies 0/21.
  All 30 results and citation sets match with sockets blocked. Case-level
  stops are request resolution, extraction, and verification.
  [Fresh acceptance checkpoint](../artifacts/phase06/SEC_ACCEPTANCE.md)

- Issue #47 verifies Netflix's three FY2022 to FY2024 revenue observations.
  The FY2024 lookup, 15.65% reported growth, and cited FY2021 absence with
  the verified FY2024 companion all reproduced offline.
  [Netflix validation](../artifacts/phase06/NETFLIX_REVENUE.md)

- Issue #48 verifies Target's three FY2021 to FY2023 revenue observations.
  The FY2023 lookup, -1.57% reported growth, and equal-length abstention
  reproduced offline with all 14 original citation responses.
  [Target validation](../artifacts/phase06/TARGET_REVENUE.md)

- Issue #49 matches all six reviewed NVIDIA revenue observations. FY2023
  through FY2025 verify against the recent original. FY2016 through FY2018
  remain provisional in the historical original. The FY2025 lookup, 114.20%
  growth, and FY2018 evidence gap reproduced offline with all 11 original
  citation responses.
  [NVIDIA validation](../artifacts/phase06/NVIDIA_REVENUE.md)

- Issue #50 verifies all nine reviewed Ford, McDonald’s, and Disney revenue
  observations. The FY2024 lookups and the FY2023 to FY2024 reported growth
  comparisons reproduced offline with their original citation responses.
  [Ford, McDonald’s, and Disney validation](../artifacts/phase06/FORD_MCDONALDS_DISNEY_REVENUE.md)

- Issue #51 adds a corrected evidence scorer for the retained Phase 6
  reports. Both passes credit the Netflix period inventory and record
  separate incomplete findings for its missing companion and NVIDIA's
  extraction stop. The retained acceptance decision still fails.
  [Scoring revision](../artifacts/phase06/SCORING_REVISION.md)

- Issue #52 requires complete result and opened citation equality for cold
  and warm acceptance replay. The synthetic controls cover ingestion
  failure and clarification, including changed payloads that block the
  score. The pinned #44 workflow reproduced its 30 historical matches.
  [Exact offline replay](../artifacts/phase06/EXACT_REPLAY.md)

- Issue #53 passes the opened #44 development gate. All 21 reviewed
  observations match extraction. Eighteen pass reusable verification and
  three historical NVIDIA observations remain provisional. Each pass
  completes 12 supported numeric answers and three grounded abstentions,
  with all 15 results and citation sets reproduced offline. Earlier
  development, collection, and browser checks pass. Apple FY2024 still
  needs applicable disclosure verification. The next evaluation uses a
  fresh issuer-disjoint cohort.
  [Continuation gate and reproduction](../artifacts/phase06/CONTINUATION_GATE.md)

- Issue #54 independently audits and seals the fresh 15-case cohort across
  six issuer families and seven preserved domestic 10-Ks. Its runner inputs
  stayed in custody until the #45 freeze. The scoring references are held
  separately. [Continuation holdout custody](../artifacts/phase06/CONTINUATION_HOLDOUT.md)

- Issue #45 evaluates the fresh #54 cohort after rechecking both seals
  against the final development inventory and freezing the runner and
  scorer. Both passes fail with 0/12 supported answers and 0/3 grounded
  abstentions, with 15/15 exact socket-blocked replays per pass. Extraction
  matches 3/21 observations and reusable verification matches 0/21.
  Thirteen cases stop at extraction and two at verification. The original
  #44 decision remains the historical baseline.
  [Second fresh decision and reproduction](../artifacts/phase06/CONTINUATION_ACCEPTANCE.md)

- Issue #57 runs the pinned Qwen2.5 1.5B selector over the full visible
  table inventory of the seven opened #54 filings and two synthetic
  controls. It selects two reviewed rows and matches 0/21 exact
  observations. The shared extractor rejects the absent-target choice.
  The independent review replays all nine cases offline.
  [Model-only run](../artifacts/phase06/REVENUE_SELECTION_MODEL.md)

- Issue #59 seals five domestic 10-K primary documents and one synthetic
  input for the SEC extraction comparison. The separate scoring archive
  holds 12 reviewed observations across three statement layouts and two
  absent-target labels. The preparation audit found zero issuer or original
  overlaps. Release awaits the final inventory recheck and comparison freeze.
  [Extraction holdout custody](../artifacts/phase06/REVENUE_SELECTION_HOLDOUT.md)
