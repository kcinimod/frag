# Issue #2 checkpoint

Implemented the scope of [Preserve and inspect a local filing](https://github.com/kcinimod/frag/issues/2).
The local workflow preserves bytes and supplied metadata, exposes them through
ingest/inspect, and rejects duplicate or conflicting evidence updates. No facts,
reporting periods, source-cell locators, or financial-verification results exist yet.

## Reproduce

Run the exact Windows PowerShell setup, test, ingest, inspect, and offline replay
commands in the root README. `local-store/` is generated and ignored; the retained
synthetic fixture and replay harness reproduce it. `source-manifest.json` records
the synthetic-only replay and source hash. Its absolute paths describe the run
machine; replay regenerates them for the current checkout.

## Evidence and limitations

Validation output is retained in `validation.txt`. The first TDD test failed
with `ModuleNotFoundError: No module named 'frag.cli'` before implementation;
subsequent workflow checks passed. Tests and replay reject socket operations in
CLI child processes, beyond uv's offline dependency mode.

Final full-suite result: 17 passed; strict mypy passed for five Python files.
Locked setup and network-blocked synthetic replay exited successfully. The exact
README ingest and both inspection examples also ran successfully in PowerShell:
they returned the same hash-based source ID and one stored source. The separate
standards and spec reviews each reported zero findings; see `REVIEW.md`.

All demonstrated source content is synthetic. There was no local original filing,
no download attempt, no source-identity authentication, and no real-source acceptance
run. Metadata is caller supplied and unverified. Input bytes are not validated as
HTML; they are preserved without decoding or execution. A correct hash establishes
byte integrity only. No extractor or verifier runs, and `facts` is empty.

## Resume

Supply the original Microsoft FY2023 10-K HTML (selected accession
0000950170-23-035122) and ingest with `--provenance local_original` and independently
confirmed identity metadata. Then proceed with the separately scoped extraction
and evidence-verification work, including reporting periods, year/value association,
unit inheritance, note context, and independent references. Phase 1 acceptance
requires the original filing, two independently verified revenue observations,
and a real-source offline replay. Later roadmap phases remain unauthorized.
