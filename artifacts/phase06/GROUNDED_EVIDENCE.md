# Grounded revenue gaps and original citations

| Preserved filing | Question in Ask the filing | Observed result |
| --- | --- | --- |
| Coca-Cola FY2024 | What was reported consolidated revenue growth from FY2021 to FY2024? | FY2021 is absent from the statement inventory, which shows FY2022–FY2024. The FY2024 cell supports USD 47,061 million. |
| Procter & Gamble FY2024 | What was reported consolidated revenue growth from FY2023 to FY2024 using equal-length fiscal years? | Growth is withheld. The two cells support USD 82,006 million and USD 84,039 million. The fiscal-calendar link opens both original inline XBRL contexts and shows the periods behind 365 and 366 days. |
| General Electric FY2018 | What was reported consolidated revenue in FY2018? | The reported observation remains provisional because the original lacks inline XBRL verification. |
| Apple FY2024 | What was revenue in FY2024? | **Incomplete.** The reported observation remains provisional pending applicable disclosure verification. |
| Microsoft FY2023 | How did reported consolidated revenue change from FY2022 to FY2023? | 6.88%. The two original cell links show USD 198,270 million and USD 211,915 million, including the original `iso4217:USD` measure. |

Fresh ingestion and socket-blocked replay matched all five results and 19
original citation responses. Chrome 158.0.8127.37 reopened all 19 links using
only the local FRAG server. The run reused Microsoft's recorded local planner
response and verified that the earlier validation record still replays its
original result. The evidence gaps resolved without planning.
[Issue #40](https://github.com/kcinimod/frag/issues/40) ·
[P&G and Coca-Cola review](../../tests/fixtures/phase06_pg_ko_review.json) ·
[Historical GE review](../../tests/fixtures/phase06_ge_hd_ups_review.json)

The issue-specific replay checks the two reviewed P&G contexts and their day
counts. The frozen Phase 5 scorer expects a week-based mismatch and disclosure
locators for its historical incompatible-period case.

Run from the repository root in PowerShell with the web dependencies,
Chrome, and Playwright available. The replay script uses the preserved
archives and temporary stores.

```powershell
npm.cmd --prefix web run build
uv run --locked --offline --with playwright python artifacts/phase06/replay_grounded_evidence.py
```
