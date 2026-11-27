# Exact offline replay for Phase 6

The continuation runner stores the complete regenerated `result` and
`citations` for each cold and warm case. This includes an empty opened
citation map and the full result for ingestion failures and clarification.
It blocks socket creation during replay. For a recorded planner transport
failure, it verifies the saved request and reconstructs the public failure
response from the recorded failure status.

Replay writes `report.json` and exits with code 2 when a case differs or
reingested evidence changes. Each case mismatch identifies the differing
payloads or gives the reason a result could not be regenerated. The
continuation scorer verifies both payloads independently and rejects a
status-only match. Object key order is immaterial. Values, array order and
every field in both payloads must agree.

From the repository root, run the synthetic acceptance controls through the
runner and scorer CLI entry points using the installed Windows environment.

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_phase06_exact_replay.py tests/test_phase06_scoring_revision.py
```

The [#44 PowerShell workflow](SEC_ACCEPTANCE.md#reproduce-on-windows)
exports its historical evaluator from the #44 commit and its production
snapshot from the original pinned revision. Its status-only replay records
remain historical. Use the
[continuation acceptance commands](../../README.md#phase-6-exact-acceptance-replay)
to run complete-payload replay through the same PowerShell entry point.
