# Phase 5 fresh SEC holdout custody

Issue #32 reserves 15 cases across seven original domestic 10-Ks from six
issuer families and four statement layouts. Each issuer contributes a
lookup and an as-reported growth question. Three additional questions cover
an absent statement year, an incompatible fiscal-period comparison, and a
visible annual observation in a historical filing that lacks inline XBRL.
The Phase 5 verification rule requires inline evidence from the supplied
original, so the historical observation remains provisional.
[Issue #32](https://github.com/kcinimod/frag/issues/32)

The originals were preserved from EDGAR. The scorer's references record
the visible amounts, reporting periods, USD scale, consolidated scope and
applicable notes. They pin the original statement, cells, period headers,
inline facts, contexts, units and disclosures by byte range and SHA-256.
SEC Company Facts corroborates 19 annual observations by accession, concept,
currency and period, including the provisional observation. The CIK audit
compared the new cohort against the Phase 5 development manifest, including
the Microsoft and Apple controls, and the hash-verified Phase 4 runner
manifest. No new issuer appeared in either prior group. The reservation
follows each CIK across amendments, alternate copies, accessions, and
related questions.

An independent scorer-side review checked all seven original hashes and
submission records, all 19 amounts and their supporting evidence, all six
growth calculations, 30 disclosures, and all 15 case joins. The review
record is in the scorer archive. The offline verifier also rejected a
modified archive, unexpected scorer material in the runner archive, and
swapped fiscal-year values.

## Release and verification

The archives are in `../FRAG-SEC-Holdout-32` on the preparation machine.
The [custody receipt](sec-holdout-receipt.json) records their SHA-256 hashes
and the preparation base. Give the runner only `runner/inputs.zip` after
freezing the protocol, thresholds, code, model and retrieval settings. Run
in an isolated workspace with access only to the runner archive and its
frozen dependencies. Keep `scorer/expected.zip` with the scorer. If a
reserved filing or answer guides a fix, retire the entire CIK group, review
a replacement, and issue a new receipt before final measurement.

From the repository root in PowerShell, verify the two archive hashes in
the scorer's environment.

```powershell
$custody = (Resolve-Path ../FRAG-SEC-Holdout-32).Path
$receiptPath = (Resolve-Path artifacts/phase05/sec-holdout-receipt.json).Path
$receipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
foreach ($bundle in @($receipt.runner_bundle, $receipt.scorer_bundle)) {
    $path = Join-Path $custody $bundle.path
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $bundle.sha256) {
        throw "Holdout archive hash mismatch for $($bundle.path)"
    }
    Write-Output "$($bundle.path) hash matches"
}
```

Then run the sealed offline verifier in the scorer's environment. It
reopens original evidence spans, checks the case joins and growth arithmetic,
and prints aggregate totals.

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
scorer_bytes = Path(scorer).read_bytes()
if sha256(scorer_bytes).hexdigest() != record['scorer_bundle']['sha256']:
    raise SystemExit('Scorer archive hash mismatch.')
with ZipFile(BytesIO(scorer_bytes)) as bundle:
    program = bundle.read('verify.py')
sys.argv = ['verify.py', receipt, runner, scorer]
exec(compile(program, 'verify.py', 'exec'), {'__name__': '__main__'})
'@ | .venv/Scripts/python.exe - $receiptPath $runner $scorer
if ($LASTEXITCODE -ne 0) { throw 'Holdout audit failed.' }
```
