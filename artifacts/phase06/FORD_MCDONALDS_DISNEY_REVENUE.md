# Ford, McDonald’s, and Disney reported consolidated revenue

The filing workflow matched all nine independently reviewed annual observations
from the opened Phase 6 cohort. Each verified amount agrees with the original
statement cell, inline XBRL context, currency and scale, and applicable filing
disclosures. The review fixture retains the original hashes and byte spans.
[Issue #50](https://github.com/kcinimod/frag/issues/50) ·
[Independent review](../../tests/fixtures/phase06_ford_mcdonalds_disney_review.json)

| Original filing | FY2022 (USD) | FY2023 (USD) | FY2024 lookup (USD) | FY2023 to FY2024 change (USD) | Reported growth |
| --- | ---: | ---: | ---: | ---: | ---: |
| [Ford](originals/f-20241231.htm.gz) | 158,057,000,000 | 176,191,000,000 | 184,992,000,000 | 8,801,000,000 | 5.00% |
| [McDonald’s](originals/mcd-20241231.htm.gz) | 23,183,000,000 | 25,494,000,000 | 25,920,000,000 | 426,000,000 | 1.67% |
| [Disney](originals/dis-20240928.htm.gz) | 82,722,000,000 | 88,898,000,000 | 91,361,000,000 | 2,463,000,000 | 2.77% |

Ford places a shared year-end above the fiscal-year columns and cites
presentation, reclassifications, and revenue disaggregation. McDonald’s places
a full date in the first fiscal-year cell and uses the same rounded presentation
for the comparative values. Disney labels its columns by year and discloses the
Saturday year-end rule and the length of each fiscal year in Note 2.

The pinned Qwen2.5-0.5B Q4_K_M planner supplied the six plans. The scorer
confirmed the verified amounts, reported comparison basis, calculation traces,
and original citations. Fresh intake and socket-blocked replay reproduced all six
results and their original citation responses.
[Saved plans, scores, and citations](ford-mcdonalds-disney-validation.json.gz)

## Reproduce in PowerShell

From the repository root, run the verification and offline replay tests.
They also check that ambiguous columns and unresolved disclosures surface
as revenue evidence gaps.

~~~powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp "build/issue50-tests-$([guid]::NewGuid().ToString('N'))" tests/test_ford_mcdonalds_disney_revenue.py
~~~

Unpack the three preserved originals for browser review.

~~~powershell
$issue50Originals = "build/issue50-originals-$([guid]::NewGuid().ToString('N'))"
.venv/Scripts/python.exe -c "import gzip, pathlib, sys; out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True); src = pathlib.Path('artifacts/phase06/originals'); [(out / name).write_bytes(gzip.decompress((src / (name + '.gz')).read_bytes())) for name in ('f-20241231.htm', 'mcd-20241231.htm', 'dis-20240928.htm')]" $issue50Originals
Get-ChildItem -LiteralPath $issue50Originals
~~~

With the local planner running, upload each HTML file in the filing workspace
with **Local original** selected. In **Ask the filing**, enter both questions.

- “What was reported consolidated revenue in FY2024?”
- “What was reported consolidated revenue growth from FY2023 to FY2024 as reported?”

Compare the answers with the table and open the statement and disclosure
citations. The growth card shows the subtraction, division, and percentage
steps. McDonald’s disclosure links are titled “Consolidation and rounding
presentation” and “REVENUE RECOGNITION.”
