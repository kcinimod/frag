# Phase 6 continuation holdout custody

Issue #54 reserves 15 questions against seven preserved domestic 10-Ks from
six issuer families. The questions cover six reported consolidated revenue
lookups, six reported growth calculations, an absent fiscal year, a displayed
observation lacking inline verification evidence, and an incompatible
equal-length comparison. The ordinary growth requests specify the as-reported
basis. [Issue #54](https://github.com/kcinimod/frag/issues/54)

The independent audit checks the original visible consolidated statements,
statement and fiscal column locations, amounts, scale, scope, and applicable
disclosures. It checks calculation operands, results, abstention reasons, and
the required verified companion observations. SEC Company Facts corroborate
periods and amounts by accession. A second transfer from EDGAR matched all
seven original hashes. The historical filing remains an inline verification
gap even though the separate SEC data corroborates its displayed amounts.

The lineage audit checks the earlier collection and development filings,
the Phase 4 and Phase 5 SEC reservations, and the opened #44 cohort. It checks
registrants, predecessors, annual filings and amendments, original hashes,
alternate copies, and cases associated with the same issuer families. The
sealed record retains the compared inventories, SEC submission indexes, and
per-original layout signatures for the final overlap recheck. A layout
signature records title placement, fiscal period-header structure, and unit
placement. [Public custody receipt](continuation-holdout-receipt.json)

The review found six distinct layout signatures, including two absent from
the development inventories. It found zero overlapping issuer families or
originals. The seven filings provide 21 reviewed annual observations.

## Release

The preparation machine holds two separate archives outside the checkout in
`../FRAG-SEC-Holdout-54`. The runner archive contains the question manifest
and original HTML. The scoring archive contains independently reviewed
references, lineages, per-original layout signatures, and the audit verifier.

The #53 opened-cohort development gate had passed when the archives were
sealed. The runner archive was held for the acceptance freeze. At freeze, recheck the
sealed inventory against the candidate's development evidence and record the
protocol, thresholds, production and evaluation revisions, runtime, retrieval,
and scorer. Once both conditions are recorded, give only the runner archive to
the isolated runner and keep the scoring archive outside its workspace.
Issue #45 completed the recheck and controlled release using this receipt.
The #44 workflow uses its historical receipt.
[Opened-cohort gate](CONTINUATION_GATE.md) · [#45 acceptance](CONTINUATION_ACCEPTANCE.md) ·
[Historical checkpoint](SEC_ACCEPTANCE.md)

## Verify the seals

Run from the repository root in scorer custody with the project's Python
environment. The command checks the recorded development gate and layout
inventory, then verifies both archives and prints aggregate counts without
starting the application or loading a model.

```powershell
$receiptPath = (Resolve-Path 'artifacts/phase06/continuation-holdout-receipt.json').Path
$receipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
foreach ($entry in @('development_gate_record', 'development_layout_inventory')) {
    $path = $receipt."${entry}_path"
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $receipt."${entry}_sha256") {
        throw "Development evidence hash mismatch for $path"
    }
}
$gate = Get-Content -Raw -LiteralPath $receipt.development_gate_record_path | ConvertFrom-Json
if ($gate.passed -ne $true) { throw 'The opened-cohort development gate did not pass.' }
$custody = (Resolve-Path $receipt.custody.location_relative_to_checkout).Path
foreach ($bundle in @($receipt.runner_bundle, $receipt.scorer_bundle)) {
    $path = Join-Path $custody $bundle.path
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $bundle.sha256) {
        throw "Holdout archive hash mismatch for $($bundle.path)"
    }
}
$runner = Join-Path $custody $receipt.runner_bundle.path
$scorer = Join-Path $custody $receipt.scorer_bundle.path
@'
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from zipfile import ZipFile

_, receipt, runner, scorer = sys.argv
record = json.loads(Path(receipt).read_bytes())
sealed = Path(scorer).read_bytes()
if sha256(sealed).hexdigest() != record["scorer_bundle"]["sha256"]:
    raise SystemExit("Scorer archive hash mismatch.")
with ZipFile(BytesIO(sealed)) as bundle:
    program = bundle.read("verify.py")
sys.argv = ["verify.py", receipt, runner, scorer]
exec(compile(program, "verify.py", "exec"), {"__name__": "__main__"})
'@ | .venv/Scripts/python.exe - $receiptPath $runner $scorer
if ($LASTEXITCODE -ne 0) { throw 'Holdout audit failed.' }
```
