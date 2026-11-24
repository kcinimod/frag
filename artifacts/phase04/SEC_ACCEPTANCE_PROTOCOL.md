# SEC holdout acceptance protocol

Evaluate the committed Phase 4 SEC pipeline through the filing-scoped workflow
from issues #22 and #23. Freeze the source, CLI and browser citation behavior,
scorer, runtime, model weights, dependencies, and protocol before transferring
the runner bundle. The runner bundle carries only questions and preserved
originals. The scorer reads independent reference data after the live and replay
reports are fixed.

## Execution

- Snapshot the committed code at the issue #24 handoff. Use the committed
  Qwen2.5-0.5B-Instruct Q4_K_M settings, including seed 42 and temperature zero.
- Hash the evaluation scripts, protocol, production Python modules, launcher,
  dependency configuration, and runtime files. Record the Python and package
  versions. Use the pinned model digest and the production runtime fingerprint
  and alias. Freeze a dedicated loopback port and confirm the server is healthy
  before running. Do one live pass in
  manifest order, with no prompt repair or retry of scored cases.
- Use a fresh workspace containing the frozen code and runner archive.
  The trusted Python runner constrains file access to that workspace and its
  interpreter environment, and the only live network destination is the
  production loopback planner. The native model server runs in offline mode.
  The runner receives no expected results.
- Pin the runner archive to the custody receipt. Validate the manifest
  structure, case IDs and issuer counts, source paths and hashes, and CIK
  disjointness against the Microsoft and Apple development issuers.
- Ingest each preserved original once via the public CLI, ask each original
  question against its selected filing with the CLI, and reopen every emitted
  citation via its public Flask route. Preserve ingestion diagnostics and
  evidence, actual model requests and proposals if used, result, trace,
  citation response, and timing. A failed command remains a case outcome.
- Replay via fresh ingestion and the public replay command against the saved
  production plans or evidence-gap records. Compare the full result and
  citation responses. The evaluation runner blocks network connections during
  replay. A recorded transport failure cannot be recreated offline and is
  explicitly counted as a replay miss.

## Scoring

Run the custody verifier and score the fixed outputs in the scorer environment.
Check original citation links using the preserved hash and visible excerpts.
Match the statement cells and their row, period header and units against the
independent byte ranges in the original. A disclosure excerpt can use different
boundaries if it contains the independently reviewed span. Report citation
support for answerable cases and for emitted answers. An empty emitted-answer
denominator is undefined.

Score lookup and growth amounts against the independently reviewed, normalized
operands and periods. Growth also requires the correct percentage to two
decimals and the correct absolute change when presented. Require any annotated
fiscal-period-length caveat for end-to-end completion. Count a correct supported
answer or a grounded abstention as complete. A grounded abstention must
identify the missing annual revenue and the affected year and withhold the
requested result. Any user-visible partial operand must be accurate and cited.
Withholding an answerable case earns no end-to-end credit. Keep all cases in
the end-to-end denominator, including command failures and insufficient
evidence. The protocol has no numerical pass threshold.

The cohort has six reserved domestic 10-K issuers and covers annual revenue,
growth, and missing annual observations. It provides no estimate for other
metrics, incompatible verified observations, or SEC filings generally.
