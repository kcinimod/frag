# SEC financial QA: implementation and acceptance checklist

Leave boxes unchecked until a command, test, citation or run record demonstrates the behavior. Suggested order: ingest one filing → verify one calculation → connect the local planner → compare one-pass and agent retrieval. Benchmark FinQA separately.

## 1. Ingest and preserve evidence
- [x] For the retained Microsoft FY2023 10-K, the accession, company, form, filing date, fiscal dates, hash, and parser version are recorded. Socket-blocked replay used the preserved bytes. [Source manifest](artifacts/phase01/source-manifest.json) · [Validation](artifacts/phase01/acceptance-validation.txt)
- [x] Both verified observations retain metric, year, currency, scale, scope, basis, row, column, parent table, source, and relevant notes. The public workflow rejects a wrong year/amount association. [Facts](artifacts/phase01/microsoft-revenue.json) · [Verification regressions](tests/test_verification_workflow.py)
- [ ] Handle merged headers, per-share exceptions, missing vs explicitly nil, consolidated vs segment, reported vs adjusted and original vs restated. Unknown symbols stay unknown until resolved.
- [ ] Separate period from publication date; exclude later restatements for historical “as of” questions. Keep original and revised facts.
- [ ] Distinguish full year, quarter and year-to-date; only difference compatible cumulative flows. Never sum balance-sheet snapshots to create a year-end balance.
- [ ] Normalize thousands/millions deterministically. Currency changes need comparable reported values or an evidenced conversion method; scale conversion alone is insufficient.
- [ ] Stable chunk IDs prevent duplicate inserts on retries. Validate parent links before publishing a new index. Pin each run to one validated snapshot and distinguish freshness from integrity.

## 2. Retrieve sufficient evidence
- [ ] Filter known company/scope/period constraints; search across publication dates that could contain the requested period. Preserve source and parent identifiers through chunking.
- [ ] Track candidates and ranks before/after reranking and exact context after truncation. Measure recall of individual facts and coverage of the complete required set.
- [ ] Deduplicate repeated facts with matching context; retain provenance, exceptions and conflicting versions. Preserve both years even if one ranks lower.
- [ ] If a header or note is missing, inspect the parent before searching again. If a year is absent, target that year. If still unsupported, say what was checked and what remains missing.
- [ ] Route structured lookups and narrative explanations separately. Stop on resolved requirements, no progress or budget. Do not confuse “not retrieved” with “does not exist.”
- [ ] Add keyword + semantic retrieval, rank fusion and reranking only after a measured comparison. Search score does not establish eligibility or citation support.

## 3. Validate the calculation and answer
- [ ] Each operand resolves to a verified fact, earlier result or justified constant. Check operator, operand role/order, output units and requested metric separately from syntax.
- [x] Validate the denominator before division in the verified revenue growth calculator. An explicitly verified zero returns an undefined percentage and a labeled absolute change. [Synthetic regression](tests/test_growth_workflow.py)
- [x] The verified revenue growth calculator returns a typed percent, operands, an operation trace, and comparison caveats. Browser citations open the original cells and notes offline. [Calculator replay](artifacts/phase02/GROWTH_HANDOFF.md)
- [x] The annual revenue lookup validates the proposed fact against the resolved fiscal year and the selected filing's verified evidence. It rejects an unsupported operation, an unknown fact ID, or a different year's verified fact. Both retained revenue citations opened offline in Chrome. [Lookup verification](artifacts/phase02/LOOKUP_HANDOFF.md) · [Lookup regressions](tests/test_lookup_workflow.py)
- [ ] Validate each claim: a citation must support the exact period and metric. Attribute management statements; separate actuals, guidance and scenarios. A coincidental numeric match does not establish support.
- [ ] Error routing: timeout → bounded retry; unsupported fact → retrieve; invalid program → targeted repair and rerun; valid program → preserve. Measure fixes minus regressions.

## 4. Minimum acceptance cases (use independent expected results)

| Test input or perturbation | Pass condition |
|---|---|
| Reported FY2022 = 800m, FY2023 = 920m; FY2024 guidance also says 15% | Returns 15% from (920−800)/800, citing both actuals. Guidance is not supporting evidence. |
| Same inputs; wrong program divides by 920 | Reject as wrong denominator even though syntax and arithmetic are valid. |
| Remove prior-year row from context, leave it in index | Recover it through a bounded follow-up and cite it. |
| Remove prior-year fact from all available sources | No growth rate; report supported FY2023 value and missing FY2022 value. |
| Prior-year revenue explicitly zero | Undefined percentage; supported absolute change. Missing prior year must produce a different status. |
| Double both revenue figures; reorder labeled rows; alter unrelated profit | Growth rate stays 15%; absolute change doubles only in the scaling test. Inspect selected fact IDs too. |
| Table says USD millions except per-share amounts | Revenue retains scale; EPS of 2.50 remains USD 2.50 per share. |
| Reindex the same source; then fix a parser bug | No duplicate records on retry; rebuild affected facts, chunks, embeddings and cached answers after the fix. |
| Historical cutoff precedes a guidance revision | Cite the forecast available at cutoff; do not use the later revision. |

## 5. Evaluate and decide what to build next
- [ ] Oracle evidence vs retrieved evidence: same questions, model, prompt and executor. Hide labels during evaluation; report oracle separately. For external benchmark claims use the official protocol.
- [ ] Held-out SEC examples cover new layouts, multiple calculation types, distractors and deliberately missing evidence. Keep document families and generated variants together for custom splits; audit official split overlap without silently changing it.
- [ ] Track answer/program accuracy, valid-program rate, input selection, citation support/completeness, unnecessary abstentions, accuracy among answered questions and coverage by difficulty. Keep failures in the end-to-end denominator.
- [ ] Save paired question-level fixes/regressions, sample sizes and run variability. Check correctness against known answers, repeatability across identical runs and robustness under controlled changes separately.
- [ ] Compare cold with cold and warm with warm; measure whole-request average/p95 latency, tokens, calls and peak memory on the actual Windows laptop. State measured versus hypothetical results.
- [ ] Add retries, reranking, repair or fine-tuning one change at a time. Set quality/resource gates on validation, freeze configuration, then evaluate on held-out tests. Keep local and benchmark metrics distinct.
- [ ] If training becomes justified: training-only demos, validated program targets, contrastive cases, meaningful paraphrases grouped before splitting. Verify chosen/rejected labels independently. An 8 GB GPU requires measurement; smaller batches cannot rescue an oversized single example.

## Phase 5 SEC acceptance

- [x] Compare the fixed development cohort across the baseline and four successive checkpoints. [Paired development results](artifacts/phase05/SEC_ACCEPTANCE.md#paired-development-comparison)
- [x] Score the full fresh holdout and replay its results offline. The initial freeze preceded opening. The runner needed a Windows launch fix and a replacement freeze after initial intake. [Freeze and run record](artifacts/phase05/SEC_ACCEPTANCE.md#windows-reproduction)
- [ ] Meet the fresh holdout acceptance thresholds. Each pass measured 0/12 supported answers and 1/3 grounded abstentions against minimums of 11 and 3. [Acceptance checkpoint](artifacts/phase05/SEC_ACCEPTANCE.md#fresh-holdout)

## Phase 6 SEC development

- [x] Freeze the pre-change production revision, planner and retrieval settings. Audit both development cohorts and replay all 60 cold and warm results and citation sets with sockets blocked. [Run records and reproduction](artifacts/phase06/README.md) · [Issuer and layout inventory](artifacts/phase06/DEVELOPMENT_LAYOUTS.md)
- [x] Verify all six reviewed P&G and Coca-Cola observations and reproduce both filings' lookup and growth answers with original citations offline. [Issue #38 evidence and checks](artifacts/phase06/PG_KO_REVENUE.md)
- [x] Match all ten reviewed GE, Home Depot, and UPS observations. Verify nine current observations, retain the historical GE observation as provisional, and replay six answers and both evidence gaps offline. [Issue #39 evidence and checks](artifacts/phase06/GE_HD_UPS_REVENUE.md)
- [x] Pass the opened development gate with all 19 reviewed extraction matches, 12 supported numeric answers and three grounded abstentions in each pass, and 60 exact socket-blocked result and citation-set matches across both cohorts. Recheck collection and browser citation behavior and retain the unresolved Apple FY2024 verification case. [Issue #42 comparison and evidence](artifacts/phase06/DEVELOPMENT_GATE.md)

## Phase 6 SEC acceptance

- [x] Independently audit and seal six fresh issuer families across at least four statement layouts. Preserve 12 answerable cases and three abstention cases in separate runner and scorer custody. [Issue #43 custody receipt and verification](artifacts/phase06/SEC_HOLDOUT.md)
- [x] Freeze the fresh protocol, thresholds, production revision, runtime, retrieval, and scorer before releasing the runner archive. [Frozen configuration](artifacts/phase06/fresh-freeze.json)
- [x] Run and score every cold and warm case, reproduce all 30 results and citation sets with sockets blocked, and record first stops, extraction, verification, timing, and Windows memory. [Issue #44 acceptance checkpoint](artifacts/phase06/SEC_ACCEPTANCE.md)
- [x] Verify all three reviewed Netflix observations from the opened cohort and replay the FY2024 lookup, FY2023 to FY2024 growth, and cited FY2021 absence with its verified FY2024 companion. [Issue #47 evidence and checks](artifacts/phase06/NETFLIX_REVENUE.md)
- [x] Pass the continuation development gate on the original #44 questions. Match 21/21 extraction observations, verify 18 with applicable notes, retain three provisional, and score 12/12 supported answers, 3/3 grounded abstentions, and 15/15 exact replays in each pass. Recheck earlier filing and collection behavior and track the Apple FY2024 gap. [Issue #53 results and reproduction](artifacts/phase06/CONTINUATION_GATE.md)
- [x] Independently audit and seal the fresh 15-case continuation cohort across six issuer families. Record layout novelty and keep the runner and scoring archives in separate custody until the acceptance freeze. [Issue #54 custody and verification](artifacts/phase06/CONTINUATION_HOLDOUT.md)
- [ ] Meet the fresh acceptance gate in both passes. Each pass produced 0/12 supported answers and 0/3 grounded abstentions against minimums of 11 and 3. [Frozen scorer output](artifacts/phase06/fresh-score.json)
