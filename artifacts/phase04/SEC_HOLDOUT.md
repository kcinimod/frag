# Held-out SEC evaluation handoff

Issue #24 reserved 18 cases from six domestic 10-K issuer families. Each
issuer contributes one reported consolidated revenue lookup, one growth
question and one unavailable-evidence case. Three fiscal column layouts are
represented. All six abstention cases concern missing annual observations.
[Issue #24](https://github.com/kcinimod/frag/issues/24)

## Evidence and custody

The preparer checked the visible statement, units, dates and consolidated
scope against the inline XBRL in each original. SEC Company Facts corroborated
12 operands by accession, concept, currency and reporting period. The
reference records pin exact byte ranges for the statement cells, inline
facts, contexts, units and applicable note excerpts. The unavailable cases
were checked against the complete preserved 10-K, including its tagged
revenue contexts. All six originals came directly from EDGAR.
[SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

The reserved material is in `../FRAG-SEC-Holdout-24`, outside the development
checkout. This repository records the two archive hashes and preparation
base in the [custody receipt](sec-holdout-receipt.json).

| Archive | Contents and access |
| --- | --- |
| `runner/inputs.zip` | The case manifest with case IDs, questions, source metadata and original hashes, plus six preserved HTML originals. Give this archive to the runner after code, model settings and protocol are frozen. |
| `scorer/expected.zip` | Expected amounts and arithmetic, original locators and notes, abstention requirements, issuer split, scoring instructions and the offline verifier. Keep this archive with the scorer. |

Use the CIK to reserve the whole issuer, including amendments, alternate
copies and related questions. The excluded development issuers are Microsoft
and Apple. Both archives are currently held by the preparer on this machine.
At the evaluation freeze, copy only the runner archive into an isolated
execution workspace where the custody directory is inaccessible. Keep the
scorer archive in the scorer's environment. If a reserved issuer's filing guides
implementation, move it into regression coverage, replace the entire issuer's
holdout material, and issue an updated receipt before final measurement.

## Offline verification

From the repository root in PowerShell, check both archives against the
receipt in the evaluator's custody environment.

```powershell
$custody = (Resolve-Path ../FRAG-SEC-Holdout-24).Path
$receipt = Get-Content artifacts/phase04/sec-holdout-receipt.json -Raw | ConvertFrom-Json
foreach ($bundle in @($receipt.runner_bundle, $receipt.scorer_bundle)) {
    $hash = (Get-FileHash -LiteralPath (Join-Path $custody $bundle.path) -Algorithm SHA256).Hash
    if ($hash -ne $bundle.sha256) { throw "Holdout archive hash mismatch for $($bundle.path)" }
    Write-Output "$($bundle.path) hash matches"
}
```

In the scorer's environment, run the offline verifier from the sealed scorer
archive. It takes the two archive paths and emits aggregate checks.

```powershell
@'
import json, pathlib, sys, zipfile
custody = pathlib.Path.cwd().parent / 'FRAG-SEC-Holdout-24'
receipt = json.loads(pathlib.Path('artifacts/phase04/sec-holdout-receipt.json').read_bytes())
runner = custody / receipt['runner_bundle']['path']
scorer = custody / receipt['scorer_bundle']['path']
with zipfile.ZipFile(scorer) as archive:
    program = archive.read('verify.py')
sys.argv = ['verify.py', str(runner), str(scorer)]
exec(compile(program, 'verify.py', 'exec'), {'__name__': '__main__'})
'@ | .venv/Scripts/python.exe -
```

The audit reopened 15 note spans and checked all 18 case joins, all six
original hashes, and the evidence and arithmetic for all 12 corroborated
operands. The holdout is ready for the later frozen evaluation run.
