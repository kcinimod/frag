# Annual SEC revenue development evidence

The development issuers for issue #22 are Microsoft (CIK 0000789019) and Apple
(CIK 0000320193). Exclude both issuers and their filing families from the
reserved SEC evaluation.

| Filing | Visible statement layout | Verified lookup observations |
| --- | --- | --- |
| Microsoft FY2023 10-K | Income Statements, shared June 30 header, separate fiscal-year row and table-level scale | FY2022 USD 198,270 million and FY2023 USD 211,915 million |
| Apple FY2023 10-K | Consolidated Statements of Operations, full dates per fiscal-year column, scale in a preamble, dollar markers inherited within each column | FY2021 USD 365,817 million, FY2022 USD 394,328 million and FY2023 USD 383,285 million |

Microsoft uses the preserved Phase 1 original and evidence. [Source manifest](../../phase01/source-manifest.json)

Apple's FY2023 10-K (accession `0000320193-23-000106`, filed 2023-11-03) came
from the EDGAR mirror after the SEC endpoint returned 403. The archive
contains the unchanged 1,558,924-byte HTML document. [SEC filing](https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm) · [Retrieved copy](https://edgar-mirror.sec-api.io/320193/000032019323000106/aapl-20230930.htm) · [Preserved archive](originals/aapl-20230930.htm.gz)

- Original SHA-256 `bda1f34435199672c16ecdf2034c650872d2cac8399ed0d179fc25450b080b90`
- Archive SHA-256 `0e0947b966571266e38d64646dd393af7100f6f5811a309c2ad9b92a424525a5`

Apple's visible values and tagged contexts were checked in the original.
The following locators are one-based character positions on HTML line 4.

| Fiscal year | Period start through end | Statement cell | Inline fact |
| --- | --- | --- | --- |
| 2021 | 2020-09-27 through 2021-09-25 | 500452 | `f-71`, `c-21` |
| 2022 | 2021-09-26 through 2022-09-24 | 499783 | `f-70`, `c-20` |
| 2023 | 2022-09-25 through 2023-09-30 | 499115 | `f-69`, `c-1` |

Note 1 covers consolidated scope, the fiscal calendar and taxes excluded
from revenue. FY2023 has 53 weeks and the comparatives each have 52 weeks.
Note 2 covers revenue recognition and product returns and incentives.
Note 13 explains geographic segment revenue. The verification reference
pins the exact note spans and filing hash. [Apple evidence reference](../../../src/frag/apple-revenue-reference.json)

## Offline validation

Run from the repository root in PowerShell after setting up the project environment.

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_development_revenue.py tests/test_lookup_workflow.py tests/test_verification_workflow.py
```

The tests exercise public ingestion, filing question, citation and
CLI replay paths. They verify that the browser API can reopen the amount,
fiscal date, currency, scale and notes from the preserved bytes after the
input file is removed. The planner in these tests supplies a fixed proposal.
Synthetic changes exercise disagreements in period, currency, scale,
consolidated scope, displayed amount and note content.

Local Chrome runs with the offline Qwen2.5-0.5B-Instruct and
Qwen2.5-1.5B-Instruct Q4_K_M planners returned the three Apple amounts in the
table above. Each answer displayed four citation links. Chrome opened the
FY2023 original cell and retrieved the Note 1 excerpt explaining the
53-week fiscal year. The filing inspector displayed Note 1 at HTML line 4,
characters 737420–745621.

The full Python suite passed 132 tests and skipped four optional FinQA
scoring tests because NumPy was unavailable. Python type checking and the
frontend build passed. The saved Phase 3 Microsoft collection replay
returned a calculated result.

To load Apple in the browser workspace, expand the checked-in archive and
ingest it into the store used by `serve`.

```powershell
.venv/Scripts/python.exe -c "import gzip,pathlib; p=pathlib.Path('artifacts/phase04/development/originals/aapl-20230930.htm.gz'); pathlib.Path('apple-fy2023.htm').write_bytes(gzip.decompress(p.read_bytes()))"
.venv/Scripts/frag.exe ingest apple-fy2023.htm --provenance local_original --company 'Apple Inc.' --accession 0000320193-23-000106 --form 10-K --filing-date 2023-11-03 --store .frag-development
.venv/Scripts/frag.exe inspect --store .frag-development
```

Start the local planner and serve the same store using the repository
workspace instructions. Select **Apple Inc.**, use **Ask the filing**
with `What was revenue in FY2023?`, and open **FY2023 Total net sales cell**
and **Note 1**. [Workspace setup](../../../README.md)

## FY2022 to FY2023 growth

Apple reported USD 394,328 million for FY2022 and USD 383,285 million for
FY2023. Their difference is negative USD 11,043 million. Dividing by the
FY2022 amount and converting to percent gives **−2.80%**. The verified pair
uses the consolidated totals as filed. Note 1 discloses that FY2023
spanned 53 weeks and FY2022 spanned 52 weeks. Management's discussion
attributes more than the entire year-over-year decline to weaker foreign
currencies.

In the filing workspace, ask `How did reported consolidated revenue change
from FY2022 to FY2023?` and expand **Operation trace and operands**.
Open **FY2022 Total net sales cell**, **FY2023 Total net sales cell**,
**Note 1**, and **Foreign currency impact** to inspect the original amounts
and disclosures. You can also use **Calculate revenue growth** with FY2022
and FY2023.

Ask `What was revenue growth from FY2020 to FY2023?` to see the missing
FY2020 observation alongside the verified FY2023 amount and citation.
Asking for FY2021 to FY2023 keeps both verified observations and explains
that those years do not match the reviewed pair.

The following checks exercise the public question, citation, and
socket-blocked CLI replay paths. They also cover the Microsoft 6.88%
regression and the synthetic verified-zero baseline, which yields an
undefined percentage and a USD 12 million absolute change.

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_development_revenue.py tests/test_growth_workflow.py tests/test_chat_growth.py
```

The saved growth record contains the proposal from Qwen2.5-0.5B-Instruct.
The missing-year record does not invoke a model. After ingesting Apple as
shown above, both records replay from the preserved original with the
planner stopped.

```powershell
.venv/Scripts/frag.exe replay-ask artifacts/phase04/development/apple-growth-fy2022-fy2023.json --store .frag-development
.venv/Scripts/frag.exe replay-ask artifacts/phase04/development/apple-growth-missing-fy2020.json --store .frag-development
```
