# SEC held-out acceptance checkpoint

The frozen rubric credited **4 of 18 held-out SEC tasks**. The workflow
provided no supported numeric answers. Review against the sealed references
found that all four credited abstentions also flagged a year whose revenue
was present. A fresh, socket-blocked replay reproduced all 18 outcomes.
[Issue #25](https://github.com/kcinimod/frag/issues/25)

| Frozen measure | Result |
| --- | ---: |
| Numeric accuracy on answerable cases | 0/12 |
| Original citation support on answerable cases | 0/12 |
| Original citation support among emitted answers | Undefined (0 emitted) |
| Grounded abstention on unavailable cases | 4/6 |
| End-to-end completion | 4/18 |
| Offline outcome and citation replay | 18/18 |

## What happened

- The workflow withheld the requested amount or calculation in all 12
  answerable cases. Five filings reached the dated statement parser, which
  could not identify a total revenue row. The sixth fell back to the
  Microsoft-specific extractor, which rejected its cover identity. The
  workflow extracted zero annual revenue facts and emitted zero citations.
- The frozen rubric credited four growth cases for withholding the result
  and emitting a structured missing-year issue. In each, the workflow also
  reported a missing observation for the year independently verified as
  present. Requiring the full gap explanation to agree with the original
  yields **0/6 grounded abstentions and 0/18 completed tasks**. The two
  unavailable lookups cited extraction failure and received no credit.
- The planner received one request. The remaining 17 cases stopped at the
  evidence checks. The planner was healthy before evaluation. The results
  primarily measure extraction and abstention behavior on these originals.
- The scorer independently audited 18 case joins, six original hashes,
  three statement layouts, 12 corroborated operands, and 15 original note
  spans. The cohort contains six domestic 10-K issuer families. Its six
  unsupported cases cover missing periods. The checkpoint makes no claim
  about incompatible observations, other metrics, or other filing families.

Ingestion took 164.1–268.2 ms per original (median 200.2 ms). Question
handling took 10.0–474.8 ms per case (median 11.9 ms). The single model
request leaves cold-versus-warm latency unmeasured. RAM and VRAM were
unmeasured.

## Freeze and retained evidence

The production base is `cadfceb91457386489d9f8c00f32951bf1235e00`.
The run used its committed Qwen2.5-0.5B-Instruct Q4_K_M planner settings on
a dedicated loopback port (18087) because the workstation's existing
planner occupied port 8087. The freeze SHA-256 is
`203a250ab2f41c47023f0a98baed5895cbe574549adceb971b5fedeb804e929f`.
The freeze lists the code, dependency, runtime, protocol, and model
fingerprints. The freeze manifest omitted two bundled verification references.
Both files came from the pinned commit in the evaluated snapshot and were
verified byte-for-byte against a fresh export. The replay setup below
explicitly checks their digests. The citation scorer checked source
positions and excerpt markers. Its positive checks did not independently
compare displayed scale or note text, and the cohort emitted no links to
exercise that branch. The sealed inputs remain in issue #24 custody.
The runner's Python file guard limited it to the dedicated snapshot and
interpreter environment. Only the scoring process opened the expected results
after live and replay outputs were fixed.

The retained bundle contains the freeze, full ingestion and question evidence,
model request and proposal, per-case citation responses, offline verification,
and scores. It also contains the initial infrastructure attempt. In that
attempt all six originals were ingested, but the evaluation guard rejected
SQLite read-only URIs before the question workflow ran. The guard was
corrected using the development control and the evaluator was frozen again.
The production code, prompts, scoring rules, and reserved material were
unchanged. Treat the held-out reports as evaluation evidence when planning
future development, under the issuer replacement rule in the custody handoff.
[Recorded evidence](sec-acceptance-25.zip)
[Acceptance protocol](SEC_ACCEPTANCE_PROTOCOL.md)
[Custody handoff](SEC_HOLDOUT.md)

## Verify the checkpoint offline

Run this from the repository root in PowerShell with the locked Windows
environment already installed and the archive layout from the custody
handoff. Use a fresh `build/sec-acceptance-25-reproduce` directory. The
recorded freeze requires the Python and dependency versions recorded in
`freeze.json`.

```powershell
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force build | Out-Null
$snapshot = Join-Path (Resolve-Path build) 'sec-acceptance-25-reproduce'
New-Item -ItemType Directory -Path $snapshot | Out-Null
git -c core.autocrlf=true archive --format=zip --output="$snapshot/base.zip" cadfceb91457386489d9f8c00f32951bf1235e00 src scripts/start-local-model.ps1 pyproject.toml uv.lock artifacts/phase04/sec-holdout-receipt.json
if ($LASTEXITCODE) { throw 'Could not export the frozen base.' }
Expand-Archive -LiteralPath "$snapshot/base.zip" -DestinationPath $snapshot
$referenceHashes = @{
    'apple-revenue-reference.json' = '5F4C43D35F8E8F0F161039C25E8B346A3F95B8EF67BE9A673C213406E286BC77'
    'microsoft-revenue-reference.json' = '3F39DDA3E492996A3980FFB2AAFA7EA0FD292AF5F26C579E6882A0C22EB6CE18'
}
foreach ($name in $referenceHashes.Keys) {
    if ((Get-FileHash -LiteralPath "$snapshot/src/frag/$name").Hash -ne $referenceHashes[$name]) {
        throw "Evidence reference differs for $name"
    }
}
git archive --format=zip --output="$snapshot/harness.zip" e296e85 -- artifacts/phase04/sec_holdout_runner.py artifacts/phase04/sec_holdout_score.py artifacts/phase04/SEC_ACCEPTANCE_PROTOCOL.md
if ($LASTEXITCODE) { throw 'Could not export the frozen evaluation harness.' }
Expand-Archive -LiteralPath "$snapshot/harness.zip" -DestinationPath $snapshot -Force
Expand-Archive -LiteralPath artifacts/phase04/sec-acceptance-25.zip -DestinationPath "$snapshot/recorded"
$custody = (Resolve-Path ../FRAG-SEC-Holdout-24).Path
Copy-Item -LiteralPath "$custody/runner/inputs.zip" -Destination "$snapshot/inputs.zip"
.venv/Scripts/python.exe "$snapshot/artifacts/phase04/sec_holdout_runner.py" replay "$snapshot/recorded/freeze.json" --inputs "$snapshot/inputs.zip" --work "$snapshot/replay" --saved-run "$snapshot/recorded/live/report.json"
if ($LASTEXITCODE) { throw 'Offline replay failed.' }
```

The replay prints `{"matched": 18}`. From the scorer environment, with the
same shell variables, verify the original scored report byte-for-byte and
score the new offline replay.

```powershell
$scorer = "$snapshot/artifacts/phase04/sec_holdout_score.py"
$frozen = "$snapshot/recorded/freeze.json"
$live = "$snapshot/recorded/live/report.json"
.venv/Scripts/python.exe $scorer "$custody/runner/inputs.zip" "$custody/scorer/expected.zip" $frozen $live "$snapshot/recorded/replay/report.json" "$snapshot/reproduced-score.json"
if ($LASTEXITCODE) { throw 'Recorded score did not reproduce.' }
if ((Get-FileHash "$snapshot/reproduced-score.json").Hash -ne (Get-FileHash "$snapshot/recorded/score.json").Hash) {
    throw 'Reproduced score differs from the recorded result.'
}
.venv/Scripts/python.exe $scorer "$custody/runner/inputs.zip" "$custody/scorer/expected.zip" $frozen $live "$snapshot/replay/report.json" "$snapshot/replay-score.json"
if ($LASTEXITCODE) { throw 'Fresh replay scoring failed.' }
```

To reproduce the review finding, use the fixed live results and the sealed
scorer archive in the custody environment. The output lists the four credited
cases with a contradicted missing-year issue and zero uncontradicted
abstentions.

```powershell
@'
import json
from pathlib import Path
import sys
from zipfile import ZipFile

recorded, scorer = map(Path, sys.argv[1:])
with ZipFile(scorer) as archive:
    expected = json.loads(archive.read("expected.json"))
labels = {row["case_id"]: row for row in expected["cases"]}
live = json.loads((recorded / "live/report.json").read_bytes())
scored = json.loads((recorded / "score.json").read_bytes())
results = {row["case"]["case_id"]: row["result"] for row in live["cases"]}
contradicted = []
for score in scored["cases"]:
    if not score["grounded_abstention"]:
        continue
    case_id = score["case_id"]
    label = labels[case_id]
    available = set(label["supporting_fact_ids"])
    years = {fact["fiscal_year"] for fact in expected["sources"][label["source_id"]]["facts"]
             if fact["fact_id"] in available}
    if any(issue["code"] == "missing" and issue["fiscal_year"] in years
           for issue in results[case_id]["issues"]):
        contradicted.append(case_id)
print(json.dumps({"contradicted": contradicted,
                  "uncontradicted_abstentions": scored["metrics"]["grounded_abstention"][0] - len(contradicted)}))
'@ | .venv/Scripts/python.exe - "$snapshot/recorded" "$custody/scorer/expected.zip"
```

The original live run used the pinned model directory, the frozen launcher,
and the same runner bundle. To repeat live execution, start the committed
launcher from the snapshot and use fresh output paths. Verify the server owns
the dedicated port and is healthy before running.

```powershell
$model = (Resolve-Path .frag-model).Path
New-Item -ItemType Junction -Path "$snapshot/.frag-model" -Target $model | Out-Null
$port = 18087
.venv/Scripts/python.exe "$snapshot/artifacts/phase04/sec_holdout_runner.py" freeze "$snapshot/freeze.json" --model-directory $model --planner-port $port
if ($LASTEXITCODE) { throw 'Freeze failed.' }
$planner = & "$snapshot/scripts/start-local-model.ps1" -Background -Port $port
try {
    $health = $null
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 1 } catch {}
        if ($health.status -eq 'ok') { break }
        if ($planner.HasExited) { throw 'Frozen local planner exited before it became healthy.' }
        Start-Sleep -Milliseconds 500
    }
    if ($health.status -ne 'ok') { throw 'Frozen local planner did not become healthy.' }
    if ((Get-NetTCPConnection -LocalPort $port -LocalAddress 127.0.0.1 -State Listen).OwningProcess -ne $planner.Id) {
        throw 'The loopback server is not the planner started from the frozen configuration.'
    }
    .venv/Scripts/python.exe "$snapshot/artifacts/phase04/sec_holdout_runner.py" run "$snapshot/freeze.json" --model-directory $model --inputs "$snapshot/inputs.zip" --work "$snapshot/live"
    if ($LASTEXITCODE) { throw 'Live holdout run failed.' }
} finally {
    if (!$planner.HasExited) { Stop-Process -Id $planner.Id }
}
```
