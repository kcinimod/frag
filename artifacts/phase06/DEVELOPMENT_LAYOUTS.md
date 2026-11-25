# Phase 6 development issuer and layout inventory

Keep all 12 issuer families below out of the fresh holdout. Use the CIK and
issuer lineage when checking amendments, alternate copies, related accessions,
and related questions. The rows describe the original visible statement.
Header placement refers to HTML table rows. Unit placement refers to the
visible statement scale, which is millions in every row.

For the layout overlap audit, compare title placement, fiscal header structure,
and unit placement together. Keep year order and the inline XBRL exception as
additional layout details. The two sets of byte spans identify the reviewed
statement, period header, and revenue row for each accession.
[Earlier development references](../phase05/expected.json) ·
[Opened cohort custody](../phase05/SEC_HOLDOUT.md)

## Earlier development originals

| Issuer family | CIK | Original | Statement title | Fiscal header | Unit placement |
| --- | --- | --- | --- | --- | --- |
| Microsoft | 0000789019 | msft-20230630.htm | Above table | Shared end date and descending years in one row | Separate row before period header |
| Apple | 0000320193 | aapl-20230930.htm, aapl-20240928.htm | Above table | Shared period label above descending full dates | Above table under title |
| Amazon | 0001018724 | amzn-20231231.htm | Above table | Shared end date above ascending years | Above table under title |
| Walmart | 0000104169 | wmt-20240131.htm | Above table | Shared end date above descending years | In year row |
| Alphabet | 0001652044 | goog-20231231.htm | Above table | Shared end date above ascending years | Above table in statement wrapper |
| Intel | 0000050863 | intc-20231230.htm | Separate preceding table | Shared period label and descending abbreviated full dates in one row | In date row |

## Opened Phase 5 originals

| Issuer family | CIK | Original | Statement title | Fiscal header | Unit placement |
| --- | --- | --- | --- | --- | --- |
| Procter & Gamble | 0000080424 | pg-20240630.htm | Above table | Shared end date and descending years in one row | In period row with shared date |
| General Electric | 0000040545 | ge-20241231.htm, ge10-k2018.htm | In statement table | Shared end date and descending years in one row | In period row with shared date |
| Coca-Cola | 0000021344 | ko-20241231.htm | Above table | Shared end date and descending years in one row | Above table under title |
| Home Depot | 0000354950 | hd-20250202.htm | Above table | Repeated fiscal labels in one row and descending years below | In fiscal-label row |
| Cisco | 0000858877 | csco-20240727.htm | Above table | Shared period label and descending full dates in one row | Above table under title |
| United Parcel Service | 0001090727 | ups-20241231.htm | Above table | Shared end date above descending years | Above table under title |

The GE FY2018 original lacks inline XBRL for the reviewed revenue observation.
Keep it in the extraction denominator and require additional evidence before
treating it as verified. The Phase 5 custody verifier also checked the opened
cohort against the Phase 4 SEC acceptance reservation. See that custody record
for the prior cohort audit and archive digest. [Phase 5 custody receipt](../phase05/sec-holdout-receipt.json)
