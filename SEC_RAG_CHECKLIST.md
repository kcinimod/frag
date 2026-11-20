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
- [ ] Validate the denominator before division; report an undefined percentage when prior revenue is genuinely zero. Offer a labeled absolute change; do not silently change formulas.
- [ ] Return cited facts, calculation, typed result and limitations. Format ratios/percentages once. Link to supporting cells/notes, not just the filing homepage.
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
