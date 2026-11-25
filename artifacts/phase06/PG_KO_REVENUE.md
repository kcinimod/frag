# Procter & Gamble and Coca-Cola revenue

The FY2024 10-Ks yield six verified consolidated revenue observations.
The tests check each statement, visible period and unit, revenue cell, and
inline fact against references copied from the opened Phase 5 scorer
archive. The original HTML bytes match the custody hashes.
[Issue #38](https://github.com/kcinimod/frag/issues/38) ·
[Reviewed references](../../tests/fixtures/phase06_pg_ko_review.json) ·
[Phase 5 custody record](../phase05/SEC_HOLDOUT.md)

| Issuer | FY2022 (USD millions) | FY2023 (USD millions) | FY2024 (USD millions) | FY2023 to FY2024 |
| --- | ---: | ---: | ---: | ---: |
| Procter & Gamble | 80,187 | 82,006 | 84,039 | 2.48% |
| Coca-Cola | 43,004 | 45,754 | 47,061 | 2.86% |

P&G's statement puts the scale and June 30 year-end in the same cell.
Note 1 supplies the basis for consolidation, revenue recognition, and
the treatment of trade promotions. Coca-Cola puts the scale above the
statement and uses the Net Operating Revenues row. Its citations cover
consolidation and intercompany eliminations in Note 1, the refranchising
disclosure in Note 2, and revenue recognition in Note 3. The as-reported
growth result includes the refranchising caveat.

The four lookup and growth questions were answered using the Phase 6
baseline model, runtime, and generation settings. All four saved results
and their citation responses matched offline, including 16 opened
citations. This run measures issue #38's two filings.
[Saved plans, traces, citations, and replay results](pg-ko-validation.json.gz)

From the repository root in PowerShell, the regression checks verify original
evidence spans, exercise the browser API and CLI, and replay saved plans
with sockets blocked.

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_shared_year_revenue.py tests/test_cisco_revenue.py
```
