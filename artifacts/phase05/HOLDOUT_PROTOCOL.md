# Phase 5 acceptance protocol

Issue #34 evaluates production revision `67dce6d` with the issue #32 sealed
runner and scorer archives. The Python runner, scorer policy, locked
dependencies, model weights, runtime files and settings are frozen by hash
before either archive is opened. The production export is isolated from the
working tree. It contains the existing Apple and Microsoft references, whose
CIKs, accessions and original hashes must differ from all holdout sources.

Run all 15 original questions in manifest order through filing-scoped
`frag ingest` and `frag ask`. Use the Phase 5 development measurement procedure
with Qwen2.5-0.5B-Instruct Q4_K_M, four CPU threads, zero GPU layers, seed 42,
temperature zero, prompt cache disabled, and unchanged context construction.
Cold is the first question after a fresh planner becomes healthy. Warm repeats
the question immediately. Question latency includes opening every citation
route. Report Windows process peak working sets and sampled device VRAM.
Replay both passes from fresh stores with every socket connection blocked.
Runner access is limited to the snapshot and its Python environment. Live
subprocesses are limited to the frozen planner command and GPU sampling.
The scorer archive remains outside the runner workspace.

Each pass must deliver at least **11 supported numeric answers** and
**3 grounded abstentions**. The strict development scorer credited 11/13
supported numeric answers and 2/2 grounded abstentions in each pass.
Applying those rates to 12 answerable and three abstention cases and rounding
up gives 11 and 3. All 15 cases remain in each denominator for overall task
completion.

Count a numeric result only when the requested observations, reported
units, scope, original citations and applicable notes agree with the
independent references. Check the calculation trace and comparison caveats.
The permitted generic comparison language describes consecutive annual
consolidated totals on the same filing basis and says reported totals include
any exchange-rate and acquisition effects. For unequal years the caveat
must report the actual reviewed week lengths. Check explicit absence against
the full statement-period reference, and retain and cite verified companion
amounts. Incompatibility needs the cited operands and the reviewed period
lengths. The historical verification case requires a clear evidence gap for
the displayed year with no absence claim. A truthful extraction or
verification gap on an answerable question remains incomplete.

Either pass fails acceptance for any wrong number, unsupported citation,
contradicted abstention reason or offline replay mismatch. Other unsupported
financial claims, partial amounts and unexpected trace output also block.
Classify incomplete cases by their first evidenced failure stage. Retain
answers, citations, intake, delivered planner evidence, proposals and
outcomes. Scoring uses originals and labels only after the frozen live and
offline runs. Release is a report outcome. Findings cannot justify changes
evaluated on this same reservation.
