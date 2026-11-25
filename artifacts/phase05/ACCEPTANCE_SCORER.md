# Phase 5 scorer and offline replay controls

Issue #33 validates the acceptance scorer on the 15 fixed development
questions and seven preserved 10-Ks. Each cold and warm pass counts all 15
questions. Independent references are read by the scorer after replay.
The frozen runner snapshot contains the questions and original filings.
The replay process blocks socket connections and uses saved plans to
recreate the results and reopen citation routes. [Issue #33](https://github.com/kcinimod/frag/issues/33)

| Measure | Cold | Warm |
| --- | ---: | ---: |
| Correct numeric answers | 12/13 | 12/13 |
| Supported citations among numeric answers | 11/12 | 11/12 |
| Grounded abstentions | 2/2 | 2/2 |
| End-to-end completions | 13/15 | 13/15 |
| Offline result and citation matches | 15/15 | 15/15 |

The scorer accepted Apple's USD 383,285 million FY2023 lookup and its
FY2020 absence with the cited FY2023 amount. It accepted Intel's equal-length
abstention with both cited amounts and the 53-week versus 52-week disclosure.
It flagged the existing Microsoft growth citations because the opened cells
omit the USD measure. Apple's FY2024 verification gap remained an incomplete
case against its independently answerable label.
[Original evidence reference](expected.json) · [Reviewed explanation text](acceptance-text.json) · [Original run](EVIDENCE_GAPS.md)

The regression controls alter copies of retained records. They cover incorrect
amounts, currencies, scales, periods, percentage units, and calculation traces.
They also cover unsupported comparison claims, partial amounts, disclosures,
statement-period links, and an extra unsupported citation. They recreate the
Phase 4 failure class by adding a missing FY2022 claim to Intel's abstention
even though its original reports FY2022 revenue. Another control injects
that claim into the displayed reason without changing its structured issue
code. Two controls put the same incorrect claim in the saved intake evidence
and displayed answer. The scorer checks those claims against the independent
text reference and records its SHA-256 with the score.
[Scorer controls](../../tests/test_phase05_acceptance.py) · [Phase 4 result](../phase04/SEC_ACCEPTANCE.md)

## Verify in PowerShell

Run from the repository root with the locked Python environment installed.
The historical development runner exports the measured source revision
before replay. The scorer requires a replay report with the digest of the
exact uncompressed live JSON.

```powershell
$replay = "build/issue33-positive-$([guid]::NewGuid())"
& artifacts/phase05/acceptance-replay.ps1 -Destination $replay
if ($LASTEXITCODE -ne 0) { throw 'Offline replay failed.' }
.venv/Scripts/python.exe artifacts/phase05/acceptance_score.py . "$replay/live.json" "$replay/replay/report.json" "$replay/acceptance-score.json"
if ($LASTEXITCODE -ne 1) { throw 'Expected the existing Microsoft citation failure.' }
.venv/Scripts/python.exe -m pytest -q tests/test_phase05_acceptance.py -p no:cacheprovider --basetemp "build/issue33-controls-$([guid]::NewGuid())"
if ($LASTEXITCODE -ne 0) { throw 'A scorer control failed.' }
```

To verify mismatches through the offline runner, alter one saved numeric result
and one saved citation excerpt. Replay recovers the independently checked
amount and the original citation text. It reports 28 of 30 matches. Each
pass has 12 of 15 end-to-end completions under these perturbations.

```powershell
$replay = "build/issue33-negative-$([guid]::NewGuid())"
$altered = "$replay-live.json"
@'
import gzip
import json
from pathlib import Path
import sys

phase = Path("artifacts/phase05")
live = json.loads(gzip.decompress((phase / "evidence-gap-live.json.gz").read_bytes()))
cases = {row["case"]["case_id"]: row for row in live["cases"]}
cases["aapl-lookup"]["cold"]["result"]["fact"]["normalized_amount"] = "383286000000"
cases["aapl-absent"]["warm"]["citations"]["current"]["text"] += "Altered excerpt.\n"
Path(sys.argv[1]).write_text(json.dumps(live), encoding="utf-8")
'@ | .venv/Scripts/python.exe - $altered
if ($LASTEXITCODE -ne 0) { throw 'Could not create negative replay controls.' }
& artifacts/phase05/acceptance-replay.ps1 -Destination $replay -LiveReport $altered
if ($LASTEXITCODE -ne 1) { throw 'Replay did not reject both controls.' }
.venv/Scripts/python.exe artifacts/phase05/acceptance_score.py . "$replay/live.json" "$replay/replay/report.json" "$replay/acceptance-score.json"
if ($LASTEXITCODE -ne 1) { throw 'Scorer did not reject the controls.' }
$report = Get-Content -Raw "$replay/replay/report.json" | ConvertFrom-Json
$cold = ($report.cases | Where-Object { $_.case.case_id -eq 'aapl-lookup' }).cold
$warm = ($report.cases | Where-Object { $_.case.case_id -eq 'aapl-absent' }).warm
if ($cold.status -ne 'mismatch' -or $cold.result.fact.normalized_amount -ne '383285000000' -or $warm.status -ne 'mismatch' -or $warm.citations.current.text.Contains('Altered excerpt.')) { throw 'Replay did not recover the original result and citation.' }
```

The fresh holdout remains sealed. The holdout run, numeric thresholds, and
release decision belong to issue #34.
[Holdout custody](SEC_HOLDOUT.md) · [Issue #34](https://github.com/kcinimod/frag/issues/34)
