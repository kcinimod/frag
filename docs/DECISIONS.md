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

## Issue #3 provisional annual revenue

The parser selects the statement heading and Total revenue label, associates
the displayed years with values through the logical table grid, and checks the
inline XBRL annual contexts for the original layout. The original document's
inline cover fields identify the supported form, entity, and report end without
requiring supplied metadata. Currency comes from the
statement's USD declaration or referenced XBRL unit. The statement scale applies
to revenue even when the disclosure also has a per-share exception. Amounts use
exact decimal strings. An unresolved amount stays null and ambiguous geometry
produces a diagnostic.

The source record keeps its byte-derived identity. The fact ID derives from
source ID, metric, and fiscal year. The SQLite catalogue stores extraction
results by source ID and parser version separately from the original source
record. Reingestion fills the current parser version while preserving earlier
results. Inspect can derive the current view in memory for older stores.

## Issue #4 independent verification

The independent reference is packaged separately from the extractor. For the
one reviewed filing, it pins the preserved source identity and fingerprints of
manually selected statement elements, contexts, note headings, and disclosure
ranges. A verified fact requires matching fields and geometry, resolvable original
markup, and bounded applicable notes. Comparison additionally requires both
observations and the reviewed comparative disclosures. The original input hash
is required for real-source acceptance. Explicitly synthetic derivatives report
per-observation reference matches while retaining provisional fact status.

The catalogue cache key combines parser and evidence versions. Observation IDs
remain byte-, metric-, and period-based. A failed per-observation annual context
leaves the other period available. Ambiguous shared statement geometry still
produces a source-level diagnostic.

## Issue #5 SEC acquisition

The download command targets the selected EDGAR document and checks the source
catalogue for a preserved SEC response before validating the user-agent
setting or opening a connection. The original bytes and catalogue record are the cache. A local
input can cite the same filing URL while retaining its local provenance, so the
download lookup uses both the URL and the `sec_download` provenance. Use
separate stores when comparing direct and locally supplied bytes to preserve
the storage contract for immutable provenance.

Requests use an operator-configured identifying user agent. Retry delays start
at one second for transient errors and respect a longer `Retry-After` within
the wait limit. A server-requested wait beyond the limit ends the command so
the next request can be scheduled separately. The workstation's direct SEC
request initially returned HTTP 403. A monitored contact succeeded on a later
attempt. [SEC acquisition record](../artifacts/phase01/SEC_ACQUISITION.md)

## Issue #6 Phase 1 acceptance evidence

The checked-in, independently reviewed mirror copy is the replay input. Its
size matches the SEC filing index and its preserved source hash pins both
verified observations. The separate direct response retains its own source hash
and provisional status. The Phase 1 manifest points to the original archive,
derived facts, and independent reference. Both replay modes use temporary
stores and emit JSON to stdout so a synthetic run cannot replace that manifest.
The replay blocks Python socket operations in each CLI process. The Phase 1
handoff marks the review checkpoint. [Phase 1 handoff](../artifacts/phase01/HANDOFF.md)

## Local planner for annual revenue lookup

Use llama.cpp b6500 and Qwen2.5-0.5B-Instruct Q4_K_M on the CPU for issue #10.
Setup verifies the runtime archive and weights against pinned SHA-256
digests. The application sends one schema-constrained request over loopback
and validates the proposed fact ID against the independently resolved fiscal
year and the selected filing's verified evidence. The model uses structured
fact fields as context. The citation viewer renders the original cell.
The process can run with the model loaded for repeated local questions.
[Lookup acceptance and measurements](../artifacts/phase02/LOOKUP_HANDOFF.md)

## Filing chatbot for reported revenue growth

Resolve the requested operation and chronological fiscal-year roles before
calling the planner. The plan must match the three-step program for the
selected filing's eligible facts. The existing calculator checks comparison
compatibility before arithmetic and returns the trace and original filing
citations for both the calculator and the chatbot. Saved chatbot plans use
`replay-ask`. The earlier `replay-lookup` command is an alias.
[Growth chat acceptance](../artifacts/phase02/CHAT_GROWTH_HANDOFF.md)

## Collection revenue lookup

Build a content-addressed collection snapshot from a single catalogue read
view using versioned extraction results. Keep the verified evidence and
distinct observations linked to their original sources and parent tables.
Resolve company, operation, and reporting period before keyword ranking and
structured selection. Pin explicit replay to the exact recorded source set
and validate its versions, candidate ranking, and outcome.
[Collection handoff](../artifacts/phase03/COLLECTION_HANDOFF.md)

## One-pass collection revenue growth

Apply the context limit to revenue observations and separately selected
comparison records and disclosures. Require a verified comparative and
current pair from one filing and route that pair through the deterministic
calculator. Keep selected verified observations and open requirements when
coverage is incomplete. Include comparison evidence in the snapshot hash
so replay detects changes to the basis and disclosures.
[Growth baseline](../artifacts/phase03/GROWTH_BASELINE.md)

## Bounded fiscal-year recovery

Use the same first-pass selection in both retrieval modes. When one year is
missing, filter already-ranked eligible candidates for that year within the
pinned snapshot. Prefer evidence from the initially selected filings so the
existing calculator can check the comparison on its original basis.

Count searches and calculations against the call budget. Check elapsed
time before and after each action and discard results that arrive past the
limit. Reuse the recorded elapsed checkpoints on offline replay so machine
speed cannot change the replayed stop reason.
[Bounded recovery validation](../artifacts/phase03/BOUNDED_RECOVERY.md)

## Bounded filing context recovery

Use a shared final context limit and allow explicit replay to constrain what
the first pass sees. Bounded retrieval follows table and disclosure references
from eligible observations in the pinned snapshot. It checks the locators
against the preserved original and counts each follow-up against the existing
budget. The calculator uses the facts and comparison evidence selected for the
answer. Keep the earlier retrieval versions replayable so the original
validation records remain reproducible.
[Phase 3 handoff](../artifacts/phase03/HANDOFF.md)

## Context for a supported partial growth result

When a fiscal year is missing, use the available context for the supported
observations' statement tables and applicable notes. Defer comparison
disclosures until both years are selected. Record this selection behavior
under a new retrieval version and preserve replay of earlier versions.
When first-pass evidence covers the requested years across separate filings,
reuse ranked candidates to check for a verified pair from the same filing.
If the calculation is deferred, return caveats supported by the selected
comparison evidence. Link applicable notes from annual revenue lookups.

## FinQA dev diagnostic records

Resolve annotation locators against the report's text and table. Include the
table header with selected data rows and record excerpts omitted by the
context budget. Keep reference labels in the scorer inputs and record the
exact request sent to the planner.

FinQA program validation limits numeric literals to the question and
delivered excerpts, permits the upstream constant vocabulary, and requires
table reductions to name a delivered data row. Record operand locations in
the execution trace. The dev coverage sample reports internal scores.

Use a separate cohort manifest to check that every expected ID has one
outcome before scoring. Submit every ID to the pinned scorer in its
prediction format, with an EOF-only prediction when no executable program
is available. Compare each translated execution with replay and reconcile
per-question matches with the upstream aggregate. Record discrepancies
when the upstream row-label syntax cannot represent a selected table row.

## Frozen FinQA evidence comparison

Use Qwen2.5-1.5B-Instruct Q4_K_M with four CPU threads and no GPU offload
for both modes. Keep zero demonstrations and one planner attempt per
question. Rank retrieved passages and table rows by distinct question
keyword overlap, including the original column headings for rows. Apply
the same 2,800-byte evidence budget in both
modes. Keep the frozen settings and full coverage as the public test
acceptance criteria and use no numeric accuracy threshold.
[Measured dev comparison and frozen protocol](../artifacts/phase04/FINQA_COMPARISON.md)

## FinQA public test checkpoints

Use the pinned test split's question order and a SQLite checkpoint keyed by
evidence mode and question ID. Commit each completed outcome in one
transaction. Compare the checkpoint's cohort, upstream hashes, and
configuration with the frozen protocol before resuming. A scored report
uses the full denominator in both modes. Keep counts internal unless the
pinned evaluator agrees with replay and the per-question and aggregate
scores reconcile in both modes.
[FinQA public test run and replay](../artifacts/phase04/FINQA_PUBLIC_TEST.md)

## SEC development issuers and fiscal periods

Use Microsoft and Apple as development issuers. Exclude their filing families
from the reserved SEC evaluation. For statements with independently dated
columns, compare year-ends with the inline XBRL duration context and the
applicable fiscal-calendar disclosure. Pin the original hash and exact note
spans before publishing a verified lookup. Evaluate compatibility separately
before using those observations for growth.
[Development evidence](../artifacts/phase04/development/README.md)

## Reported revenue growth on development 10-Ks

For issue #23, pin the reviewed FY2022 and FY2023 pair in the Apple FY2023
10-K. Keep FY2021 available as a standalone verified observation. The
calculation uses reported consolidated totals and cites the fiscal-calendar
and foreign-currency disclosures. Resolve evidence gaps before invoking the planner, and
retain the available verified operands and their original citations.
[Development growth and replay](../artifacts/phase04/development/README.md#fy2022-to-fy2023-growth)

## SEC holdout custody

Keep the reserved originals and questions in a runner archive outside the
development checkout. Store expected results and citation locators in a
separate scorer archive. Record the archive hashes in the repository and
release the runner archive only after the evaluation freeze. Replace the
whole issuer group if a reserved filing is used in development.
[Holdout handoff](../artifacts/phase04/SEC_HOLDOUT.md)

## Score the SEC holdout through the filing workflow

Use the committed filing-scoped CLI and original browser citation routes.
Freeze the runner, scorer, model settings, and rubric before the blinded
run. Count evidence gaps on answerable cases as end-to-end misses. Require
the missing year and the missing annual observation for abstention credit.
Retain the run and offline replay separately from the FinQA benchmark.
[SEC held-out acceptance checkpoint](../artifacts/phase04/SEC_ACCEPTANCE.md)

## Keep Phase 5 development comparisons on fixed filing inputs

Reuse the 15 development questions, original filing hashes, and scoring
references from issue #27 across the Phase 5 checkpoints. Record each
production configuration separately and report extraction and verification
before comparing question results. Use the development CIKs to exclude the
entire issuer families from the fresh holdout.
[Phase 5 development baseline](../artifacts/phase05/README.md)

## Verify shared year-end statements observation by observation

Associate fiscal years with revenue cells through the visible statement grid.
Require the inline SEC CIK, annual duration, unit, scale, and amount to agree
with the statement and require accounting-policy evidence. Preserve a
provisional visible observation and locator when inline verification fails.
Keep comparison compatibility unresolved until the evidence establishes it.
[Unseen-issuer lookup checkpoint](../artifacts/phase05/UNSEEN_LOOKUP.md)

## Verify separately titled statements with fiscal-calendar disclosures

Associate the adjacent title, combined period and scale header, and dated
revenue cells. Check the issuer identified by the consolidation disclosure
against the cover and inline SEC CIK, and assess the disclosed week count
against each annual context. Keep a visible observation provisional when
its disclosure or context does not establish agreement.
[Development layout verification](../artifacts/phase05/DEVELOPMENT_LAYOUTS.md)

## Establish original-evidence growth compatibility for a filing's latest pair

Use the current and immediately preceding annual columns in the same
consolidated statement. Require verified observations, consecutive periods,
and agreement on the revenue concept. Preserve original disclosures that
qualify comparability with the withheld growth result. A disclosed 52-week
and 53-week pair can support growth on the reported calendar. A request for
equal-length years requires matching durations. Both independently verified
amounts remain available for lookup.
[Verified growth checkpoint](../artifacts/phase05/VERIFIED_GROWTH.md)

## Establish year absence from the statement headers

Capture the displayed annual periods and source locators before verifying
individual revenue observations. An absence claim requires a complete
period inventory from the relevant consolidated statement. If a year is
displayed or the period inventory is unresolved, a missing verified
observation is an evidence gap. Retain independently verified growth
operands with their statement and disclosure citations.
[Evidence gap checkpoint](../artifacts/phase05/EVIDENCE_GAPS.md)

## Base SEC acceptance on cited answers and grounded abstentions

Require 11 supported numeric answers and three grounded abstentions per
pass, derived from the independent development score. Keep all cases in
the denominator and treat wrong numbers, unsupported citations, contradicted
reasons and replay mismatches as blocking. The fresh cohort failed the gate
at statement extraction. The evaluation gives no basis for a planner or
retrieval change. Replace any issuer family used in subsequent development
before another acceptance measurement.
[Frozen protocol](../artifacts/phase05/HOLDOUT_PROTOCOL.md) ·
[Measured checkpoint](../artifacts/phase05/SEC_ACCEPTANCE.md)

### Freeze the Phase 6 development baseline (#36)

Use committed production revision `96fa9501f9f383d9586c165cfcda78e3323b4401`
for the pre-change run. It shares the Phase 5 acceptance production bytes
and uses the same Qwen2.5-0.5B weights, runtime, and retrieval settings.
Keep those settings through the first comparison and retain the Phase 5
acceptance evidence. Audit all 12 development issuer families and their
statement, header, and unit placement combinations before opening fresh
evaluation inputs.
[Phase 6 freeze and measurements](../artifacts/phase06/README.md)

### Establish dated revenue columns from the visible statement (#37)

Associate full dates and split month/day and year cells by visible table
columns. Preserve original locators for both parts of a split date and
inherit the scale from the statement’s unit declaration. Check the inline
amount, currency, and fiscal context against the visible observation. Use
the fiscal calendar and revenue policy notes for verification. Cite the
applicable acquisition and pro forma disclosures for the reported
comparison. Keep the existing reviewed Apple evidence path for its issuer.
[Cisco implementation issue](https://github.com/kcinimod/frag/issues/37)

### Associate fiscal years beside a shared year-end (#38)

Use the visible cell spans when a shared year-end and its fiscal years
appear in the same row. Read the scale from the shared cell or the
statement's preamble, and check annual inline contexts and USD against
the original. Resolve split or cross-referenced accounting notes from
their visible headings and cited text. Carry the refranchising disclosure
into Coca-Cola's reported growth caveats.
[Issue #38 evidence and checks](../artifacts/phase06/PG_KO_REVENUE.md)

### Preserve fiscal labels and week-based reporting dates (#39)

Keep a displayed fiscal label with its observation even when the period ends
in the next calendar year. For the split Fiscal header, associate labels by
column and derive the periods from the cover date and disclosed fiscal
calendar. Require the inline context to agree with those periods. Use the
shared visible statement path for titles inside or outside the table and
retain visible observations with an explicit verification gap when the inline
evidence is missing.
[Issue #39 evidence and checks](../artifacts/phase06/GE_HD_UPS_REVENUE.md)

### Cite original fiscal dates for unequal day counts (#40)

When an equal-length request is withheld over different day counts, link
the verified inline contexts alongside the two original revenue cells.
The dates let readers check the inclusive day counts and keep the filed
amounts available. Preserve the citation shape of earlier validation
records through replay.
[Issue #40 evidence and checks](../artifacts/phase06/GROUNDED_EVIDENCE.md)
