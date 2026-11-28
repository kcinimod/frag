# Rules-only extraction development replay

Issues [#62](https://github.com/kcinimod/frag/issues/62) and
[#63](https://github.com/kcinimod/frag/issues/63) extend the standalone
offline extractor. The selector can qualify an unfamiliar label from
consistent company-wide annual revenue tags on the consolidated statement.
Dates listed above the table can be associated with the physical fiscal-year
columns and checked against the inline XBRL contexts for the selected cells.

| Opened development inputs | Prior exact | Current exact |
| --- | ---: | ---: |
| Seven filings from #54 | 12/21 | 18/21 |
| Four target-present filings from #59 | 9/12 | 12/12 |
| Two absent-target inputs from #59 | 2/2 abstentions | 2/2 abstentions |

The newly exact observations are PepsiCo FY2022–FY2024, Adobe FY2022–FY2024
from its FY2024 filing, and Kroger FY2021–FY2023. Kroger's FY2023
ended February 3, 2024 and spanned 53 weeks. All 30 exact observations
remain provisional. The historical Adobe filing still supplies its displayed
amounts and year-ends, with unresolved starts in the automated run. Its
independently reviewed fiscal calendar remains available in the #54 scoring
archive.

The replay checks the runner and scorer archive seals and each original
hash, then scores the extracted amounts, full periods, scope, currency,
scale, and original locators against the independent references. Run from
the repository root with both opened custody bundles available.

```powershell
$out = Join-Path 'build' ('extraction-followups-' + [guid]::NewGuid() + '.json')
.venv/Scripts/python.exe artifacts/phase06/revenue_extraction_followups.py ../FRAG-SEC-Holdout-54 ../FRAG-SEC-Holdout-59 $out
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Get-FileHash -LiteralPath $out
```

The socket-blocked replay JSON SHA-256 is
`de04a478327eccfe2268bd89ac2fe5e88b4955cbe87ba95d16817bcf732bab3e`.
The [frozen #60 result](REVENUE_SELECTION_ACCEPTANCE.md) remains the
historical holdout score. A freshly reserved, issuer-disjoint cohort is
needed for the next generalization measurement.
