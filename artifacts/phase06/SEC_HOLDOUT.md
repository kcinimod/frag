# Phase 6 fresh SEC holdout custody

Issue #43 reserves six issuer families across seven preserved domestic EDGAR
10-Ks. The 15 questions comprise six revenue lookups, six reported growth
calculations, and three abstention cases. The abstentions cover an absent
fiscal year, a displayed observation lacking verification evidence, and an
incompatible comparison. The development gate passed in issue #42.
Issue #44 owns the acceptance freeze and evaluation.
[Issue #43](https://github.com/kcinimod/frag/issues/43) ·
[Development gate](DEVELOPMENT_GATE.md) ·
[Issue #44](https://github.com/kcinimod/frag/issues/44)

The custodian prepared the references from the original visible statements,
inline facts and fiscal contexts, applicable notes, and SEC Company Facts.
A separate reviewer audited the filing identities and original hashes, issuer
lineage and overlapping accessions, amendments, copies and cases, statement
layouts, amounts and supporting locators, notes, growth calculations, and
abstention reasons. The full review and issuer-specific findings are sealed
with the scoring references. The [receipt](sec-holdout-receipt.json) records
the aggregate coverage and binds both archives to their SHA-256 digests.
Its development digests cover the exact bytes of the machine-readable gate
score and layout inventory.
[Gate score](gate-score.json) · [Layout inventory](DEVELOPMENT_LAYOUTS.md)

The independent audit found four distinct statement layout signatures. Two
are absent from the development inventory. It found zero overlapping issuer
families or originals and checked 21 observations, 146 original evidence
spans, 22 note excerpts, and all 15 cases. A second transfer from official
EDGAR matched every original SHA-256. The verifier passed on both sealed
archives and rejected altered hashes, a scorer file inserted into the runner
archive, and swapped fiscal-year amounts.

## Release

The archives are in `../FRAG-SEC-Holdout-43` on the preparation machine.
The runner archive holds the original filing bytes and question manifest.
The scorer archive holds the expected results, corroborating evidence, audit
and offline verifier. Give the isolated runner only `runner/inputs.zip` after
recording the freeze of the protocol, thresholds, production revision,
runtime and retrieval settings, and scoring policy. Keep
`scorer/expected.zip` in scorer custody. Carry this public record into any
implementation of issue #44 and keep the preparation and review transcripts
in custody.

The scorer's `expected.json` keys cases by runner case ID and sources by
accession. Evidence locators are zero-based byte ranges with exclusive end
offsets and SHA-256 digests. Use the reviewed scale and full annual header
inventory when validating citations. The inherited Phase 5 helpers assume
millions and a literal “year ended” label. Freeze any generic changes to
those checks using development evidence or labeled synthetic controls before
releasing the runner archive.

## Verify the seals

From the repository root in PowerShell, check both hashes before opening
either archive. Run these commands in custody.

```powershell
$receiptPath = (Resolve-Path artifacts/phase06/sec-holdout-receipt.json).Path
$receipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
$custody = (Resolve-Path $receipt.custody.location_relative_to_checkout).Path
foreach ($bundle in @($receipt.runner_bundle, $receipt.scorer_bundle)) {
    $path = Join-Path $custody $bundle.path
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $bundle.sha256) {
        throw "Holdout archive hash mismatch for $($bundle.path)"
    }
    Write-Output "$($bundle.path) hash matches"
}
```

In the scorer's environment, run the offline custody verifier from the
hash-checked scorer archive. It prints aggregate results and requires
neither the application nor a model.

```powershell
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
