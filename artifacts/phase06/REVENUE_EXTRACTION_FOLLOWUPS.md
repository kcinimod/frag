# Rules-only extraction development replay

Issues [#62](https://github.com/kcinimod/frag/issues/62) and
[#63](https://github.com/kcinimod/frag/issues/63) extend the standalone
offline extractor. The selector can qualify an unfamiliar label from
consistent company-wide annual revenue tags on the consolidated statement.
Dates listed above the table can be associated with the physical fiscal-year
columns and checked against the inline XBRL contexts for the selected cells.

| Opened development inputs | Prior exact | Current exact |
| --- | ---: | ---: |
| Seven filings from #54 | 12/21 | 21/21 |
| Four target-present filings from #59 | 9/12 | 12/12 |
| Two absent-target inputs from #59 | 2/2 abstentions | 2/2 abstentions |

The newly exact observations are PepsiCo FY2022–FY2024, Adobe FY2022–FY2024
from its FY2024 filing, Adobe FY2015–FY2017 from its FY2017 filing, and
Kroger FY2021–FY2023. Kroger's FY2023 ended February 3, 2024 and spanned
53 weeks. Adobe FY2017 has no inline XBRL revenue tags. Its fiscal calendar
note and displayed year-ends establish its period starts. All 33 exact
observations remain provisional.

The replay checks the runner and scorer archive seals and each original
hash, then scores the extracted amounts, full periods, scope, currency,
scale, and original locators against the independent references. It also
submits each independently reviewed row directly to the period extractor.
Run from the repository root with both opened custody bundles available.

```powershell
New-Item -ItemType Directory -Path build -Force | Out-Null
$out = Join-Path 'build' ('extraction-followups-' + [guid]::NewGuid() + '.json')
.venv/Scripts/python.exe artifacts/phase06/revenue_extraction_followups.py ../FRAG-SEC-Holdout-54 ../FRAG-SEC-Holdout-59 $out
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Get-FileHash -LiteralPath $out
```

The socket-blocked replay JSON SHA-256 is
`05f838d0507dcedefb781b2ac185d15cd0604bb5e1f01a98635ca6ed52bea272`.
The [frozen #60 result](REVENUE_SELECTION_ACCEPTANCE.md) remains the
historical holdout score. The subsequent fresh four-issuer check matched
0 of 12 observations for both extraction revisions.
[Fresh results and replay](REVENUE_EXTRACTION_FRESH.md)
