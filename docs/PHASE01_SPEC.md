# Phase 1: preserve and verify Microsoft's annual revenue evidence

Specification with the primary testing boundary confirmed by the user for publication to GitHub with the `ready-for-agent` label. This specification authorizes no work beyond Phase 1.

## Problem Statement

A local SEC financial QA assistant needs trustworthy financial observations before it can calculate or answer questions. A correctly parsed number is insufficient when its reporting period, currency, scale, consolidation scope, accounting basis, applicable notes, or source location is wrong or missing. The repository currently has requirements and design decisions but no application, tests, or demonstrated ingestion run.

The first milestone must establish reproducible evidence for Microsoft's reported consolidated revenue for FY2022 and FY2023, using both observations from its FY2023 10-K. It must distinguish provisional extraction from verified facts and preserve enough original evidence to audit every published observation offline.

## Solution

Provide a small, deterministic Python package and command-line workflow to ingest the selected original filing, preserve its bytes and metadata, inspect extracted revenue observations and supporting evidence, and replay the workflow offline. Accept downloaded or locally supplied original HTML. Verify observations independently against the original cells, headers, reporting contexts, and applicable notes.

Deliver a reproducible evidence bundle and an accurate handoff. Successful Phase 1 acceptance requires both real-source observations to pass verification, a real ingestion run, and an offline replay. If source access or verification remains blocked, deliver an explicitly incomplete checkpoint with supported partial observations and exact remaining steps.

## User Stories

1. As a local analyst, I want to ingest the selected Microsoft FY2023 10-K, so that both annual revenue observations come from the same filing and reporting basis.
2. As a local analyst, I want to supply original HTML from disk, so that unavailable downloads do not prevent local ingestion work.
3. As a local analyst, I want downloads to use an identifying SEC user agent, caching, and bounded backoff, so that source acquisition follows SEC access guidance.
4. As an auditor, I want original filing bytes preserved separately from derived records, so that I can inspect unchanged source evidence.
5. As an auditor, I want company identity, accession, form, filing date, source URL, source hash, and parser version recorded, so that each run has reproducible provenance.
6. As a local analyst, I want FY2022 and FY2023 values associated with the correct visible year headers, so that a numeric match under the wrong header cannot pass verification.
7. As a local analyst, I want annual reporting dates recorded separately from publication dates, so that a filing date cannot be mistaken for a reporting period.
8. As a local analyst, I want original labels and raw values retained beside normalized amounts, so that transformations remain auditable.
9. As a local analyst, I want currency and scale inherited from the correct table context, so that millions and per-share exceptions cannot distort revenue.
10. As a local analyst, I want reported consolidated revenue distinguished from segment, adjusted, organic, and constant-currency measures, so that the observation preserves its actual meaning.
11. As an auditor, I want table, row, column, cell, header, and applicable-note locators resolvable in the saved source, so that I can validate exact supporting evidence.
12. As a local analyst, I want acquisition-related scope caveats, including Nuance, retained, so that the observations do not imply constant-scope comparability.
13. As a local analyst, I want the FY2022 comparative and relevant recast or restatement disclosures retained, so that incompatible revenue definitions leave comparison unresolved.
14. As a local analyst, I want uncertain values and context explicitly represented as unknown, so that missing information is never silently guessed or treated as zero.
15. As an auditor, I want provisional facts distinguished from verified facts, so that successful parsing alone cannot publish unsupported evidence.
16. As an auditor, I want verification decisions made per observation, so that a verified FY2023 fact remains available when FY2022 is unresolved without implying full milestone completion.
17. As an auditor, I want independent reference observations grounded in original source inspection, so that repeating the extractor cannot masquerade as correctness verification.
18. As a local analyst, I want an inspection command exposing machine-readable facts, provenance, status, and unresolved requirements, so that I can review supported and incomplete results.
19. As a local analyst, I want reingestion of identical input to preserve stable identifiers and avoid duplicate records, so that retries are safe.
20. As a local analyst, I want parser and evidence versions retained with derived records, so that changed extraction behavior cannot silently reuse stale results.
21. As a local analyst, I want cached ingestion and inspection to run with networking disabled, so that offline reproducibility is demonstrated.
22. As a maintainer, I want unsupported layouts and uncertain table geometry rejected explicitly, so that the initial parser makes only evidence-backed support claims.
23. As a maintainer, I want regression coverage for merged headers, inherited units, earlier-row rowspans, and missing intervening note headings, so that known evidence-association failures cannot silently recur.
24. As a maintainer, I want synthetic fixtures identified and distinguished from original filing evidence, so that synthetic tests cannot be reported as real-source acceptance.
25. As a Windows developer, I want verified PowerShell commands for dependency setup, tests, ingestion, inspection, and offline replay, so that I can reproduce the workflow locally.
26. As a reviewer, I want facts, a source manifest, validation output, and a restart-safe handoff, so that I can distinguish implemented behavior, passing checks, real-source verification, and remaining blockers.
27. As a reviewer, I want acceptance checklist updates linked to actual evidence, so that completion claims reflect demonstrated results.
28. As the project owner, I want implementation to stop after Phase 1 for review, so that calculation, retrieval, and model work remains separately authorized.
29. As a reviewer, I want each feature issue to include a browser workflow or observable result in one evolving local app, so that I can review the feature as it lands.

## Implementation Decisions

- Use Python, uv, a committed dependency lockfile, local storage, and a CLI on Windows. Keep dependencies lean and production logic importable outside notebooks. No inference service or model is needed for this phase.
- Run the browser app on localhost through uv after building its TypeScript frontend. The browser calls a local Python API, and the API and CLI share the same Python operations and source store. The first slice follows closed issue #2 and provides browser upload and source inspection. Issue #3 extends that source view with provisional revenue facts and supporting evidence. Add richer evidence interactions in later slices as their features require them.
- Separate source acquisition and preservation, deterministic extraction and normalization, evidence verification, persistence, and CLI orchestration behind reusable modules. Exact module boundaries remain implementation choices; no existing application interfaces constrain them.
- The selected source is Microsoft Corporation's FY2023 10-K, accession 0000950170-23-035122. The design record identifies CIK 789019, filing date July 27, 2023, and report end June 30, 2023. Confirm identity and exact contexts against preserved original evidence during implementation.
- Take both annual observations from that filing's consolidated income statement. Preserve the FY2022 comparative on the filing's reporting basis, together with relevant reclassification or restatement disclosures.
- Support one documented layout initially, based on inspection of original HTML. Select revenue using semantic evidence and context rather than fixed row position or hard-coded expected amounts. Additional layout support requires additional real-file regression evidence.
- Preserve original bytes without rewriting them, compute their source hash, and keep derived facts and run records separate. Local input must retain explicit provenance; locally supplied original HTML is valid real-source input, while a synthetic document is not a filing.
- Consult current official SEC access guidance when implementing downloads. Configure an identifying user agent, cache successful acquisition, and bound retries and backoff. Do not require a successful download when original HTML is available locally.
- Each fact records stable fact and source identifiers, company, metric and original label, raw and normalized amounts, currency, scale, reporting period, annual context, basis, consolidation scope, parent table identifier, source locators, applicable-note references, parser version, and verification status with unresolved requirements. Store unknowns explicitly.
- Source locators must resolve against saved original evidence and identify supporting table geometry, year headers, cells, and bounded applicable notes. A correct digit sequence with an incorrect year association fails verification.
- Preserve accounting-policy, revenue-recognition, consolidation, recast, acquisition, and scope evidence relevant to interpreting the observations. The design record identifies Notes 1, 8, and 19 as inspection candidates; their sufficiency and boundaries require original-source inspection.
- Verification requires independent reference observations established from original cells, headers, contexts, and applicable notes. Keep those reference records separate from extractor output. References may contain independently checked expected values; production extraction must not encode those values.
- Verification is per observation. Unknown geometry, ambiguous note boundaries, or unresolved required context prevents verified status. Preserve provisional extraction for inspection where possible. Unsupported input must produce an explicit diagnostic rather than guessed facts.
- Validate compatibility of the two observations' revenue definitions and reporting periods. Preserve acquisition and exchange-rate caveats; reported consolidated revenue does not establish organic growth, constant-currency growth, or constant acquisition scope. An unresolved comparison keeps the full deliverable incomplete.
- Reingestion of unchanged source with the same parser preserves stable logical identifiers and introduces no duplicate facts or sources. Record source and parser versions so changes do not silently reuse stale derived evidence; preserve original source records.
- Provide ingest and inspect commands with machine-readable records and useful diagnostics. Offline replay must use preserved input and require no network access.
- Deliver Phase 1 facts, a source manifest, validation output, reproduction instructions, and a short handoff in the designated Phase 1 artifact area. Maintain project status and a decision log. Record exact commands, outcomes, limitations, and the next milestone; only evidence-backed acceptance items may be completed.
- If source access fails, complete and test local-file ingestion and record the acquisition blocker and remaining command. If no original filing is available, synthetic-only success is an incomplete checkpoint. Partial verification is also an incomplete two-year deliverable.
- Treat filing content as data. Stop after the Phase 1 handoff for review. An ADR is needed only when an actual consequential decision with a meaningful trade-off is settled.

## Testing Decisions

- Review each feature through its observable browser behavior. For the first UI slice, confirm that upload and inspection work without internet access, identical uploads deduplicate, conflicting submissions preserve the existing record, and CLI and browser can inspect sources created by either entry point.

- Confirmed primary testing boundary: the public ingest-and-inspect workflow, exercised with original or explicitly synthetic HTML, source metadata, a temporary local store, and inspection of the resulting facts and saved evidence. Prefer this single high-level boundary over tests tied to parser helpers or database internals. Production logic remains importable.
- Exercise acquisition, extraction, normalization, evidence verification, persistence, and CLI orchestration through externally observable outcomes: records, statuses, diagnostics, source preservation, resolvable locators, and replay behavior. Use controlled acquisition responses for transport failures; the real-source acceptance run remains separate from deterministic regression tests.
- No application tests or established test patterns exist. The requirements checklist and completed design discussion supply acceptance cases; meaningful new tests should verify behavior independently rather than mirror implementation.
- Establish reference observations by independent inspection of original cells, year headers, units, annual contexts, and bounded applicable notes. Record how references were established. Repeating the same parser is evidence of repeatability only.
- Verify both annual observations against independent references, including reporting dates, scale, normalized amounts, scope, basis, and evidence locators. Do not mark either fact verified merely because its amount matches.
- Test year/value association under merged headers, labeled-row reordering, unrelated numeric distractors, and an earlier-row rowspan that affects year columns. Accept correct association or explicit unsupported/uncertain status; never accept a verified fact assigned to the wrong year.
- Test inherited currency and scale, including a table with a per-share exception, to ensure revenue normalization remains correct. Include unresolved symbols or missing amounts and ensure they remain explicit unknowns rather than zero.
- Remove or obscure an intervening note heading and ensure an uncertain applicable-note boundary cannot yield verified status. Check that note and cell locators resolve against preserved evidence.
- Test consolidated-versus-segment selection, annual-period identity, retention of comparative/recast evidence, and unresolved compatibility. Do not claim broader filing-layout or historical-query support from these bounded cases.
- Test verification independently for the two observations: one may be verified while the other remains provisional, but the full Phase 1 milestone must remain incomplete.
- Ingest identical source twice and assert stable identifiers and no duplicates. Confirm recorded source/parser versions make changed input or changed extraction behavior distinguishable.
- Test locally supplied input, cache reuse, source-byte preservation and hashing, explicit acquisition failure, and offline replay with network access disabled. Assert cached or local replay requires no download.
- Keep a small, labeled regression fixture set. Synthetic cases exercise controlled perturbations; acceptance requires preserved original filing evidence, one real ingestion run, independently supported facts for both years, and one offline replay.
- Capture actual test output and run records. Verify documented Windows PowerShell commands before describing them as runnable. Never report unexecuted checks or synthetic-only runs as real-source acceptance.

## Out of Scope

- Revenue-growth calculation, percentage answers, or a general numerical executor; these begin in Phase 2 after review.
- Local-model planning, model downloads, hosted inference, cloud fallback, training, or fine-tuning.
- Retrieval, embeddings, vector indexes, reranking, bounded agents, or answering arbitrary filing questions.
- FinQA, FinanceBench, leaderboard claims, or broader end-to-end benchmark work.
- Hosted UI deployment, a general-purpose SEC parser, additional companies or filing layouts without explicit subsequent scope, or full historical as-of query support.
- Organic-growth, constant-currency, constant-scope, causal, or forecast claims inferred from reported consolidated revenue.
- Completing later-phase checklist items or claiming general correctness from the single supported filing.

## Further Notes

- This draft synthesizes the repository's implementation requirements, evidence checklist, completed Phase 1 design discussion, and established glossary. No application or extraction run has been demonstrated yet, and no existing GitHub issues were found during preparation.
- The selected source's identity and previously researched observations are design inputs, not a claim that original bytes have been acquired or verified locally. Exact reporting contexts, supported geometry, note boundaries, and real-source correctness remain implementation facts to establish.
- The design discussion records an explicit shared-understanding checkpoint before implementation. Publishing this specification does not begin implementation or complete Phase 1 acceptance.
- The user confirmed the primary testing boundary. Publish this specification as a GitHub issue in the configured repository with `ready-for-agent`. Ticket decomposition and implementation are subsequent steps.
