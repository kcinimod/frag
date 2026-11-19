# Issue #4 revenue verification

Both observations from the preserved Microsoft FY2023 Form 10-K passed
independent checks. The comparison is compatible on the filing's reported
consolidated US GAAP basis. FY2022 is the comparative presented in the FY2023
filing. [Offline replay record](microsoft-revenue.json)

| Reporting period | Statement markup | Reported USD millions |
| --- | --- | ---: |
| 2021-07-01 through 2022-06-30 | FY2022 header line 4314, value line 4403 | 198,270 |
| 2022-07-01 through 2023-06-30 | FY2023 header line 4311, value line 4399 | 211,915 |

## How the reference was established

Read the retained filing as raw HTML and inspected the visible Income Statements
heading (line 4267), the millions disclosure with its per-share exception (4286),
the June 30 annual heading (4309), the merged year cells and the Total revenue
row (4396). Counted the physical cells and followed their column spans to the
paired year headers. Read the inline tags on both revenue cells and followed each
context ID to line 8. Each context has the Microsoft CIK, a July 1 start and June 30
end, and an undimensioned entity. Both cells use the USD measure and scale six.
The cover's CIK, form and report-period tags corroborate filing identity.
Fingerprints cover those reviewed fragments. The reference was recorded from
the original markup independently of the extraction workflow.
[Independent reference](../../src/frag/microsoft-revenue-reference.json)

Read the successive headings in the Notes to Financial Statements and matched
the end of each applicable range to the next note or the auditor report heading.
The ranges below use inclusive line numbers. The machine-readable locators use
an exclusive end.

| Filing evidence | Lines | Interpretation |
| --- | --- | --- |
| Note 1, Accounting Policies | 7233–7607 | US GAAP, consolidated subsidiaries and intercompany eliminations, transfer-of-control revenue recognition, annual-average currency translation, and disclosed recasts with no impact on the consolidated income statements. |
| Note 8, Business Combinations | 13913–14338 | Nuance entered consolidation March 4, 2022. FY2022 therefore includes a partial year and FY2023 a full year. ZeniMax entered before both periods. Activision Blizzard was pending at filing. |
| Note 13, Unearned Revenue | 17612–17826 | Contract liabilities and remaining performance obligations provide supporting context for when revenue is recognized. |
| Note 19, Segment Information and Geographic Data | 20936–21845 | Segment amounts were recast for internal reporting. The segment, geographic, and offering tables corroborate both consolidated totals. |
| Item 7, MD&A | 1909–1911, 2315–2323, 2671 | Corroborates the segment recast, records foreign currency effects, and identifies Xandr in a component revenue discussion. |

The scope and exchange-rate caveats accompany the reported observations.
Compatibility applies to the annual periods and the reported revenue definition.
The comparison contains no calculated growth or acquisition or currency adjustments.

## Provenance and replay

The SEC index corroborates the CIK, accession, filing and report dates, and
the exact 9,963,591-byte primary document size. The retained bytes came from an
EDGAR mirror and have SHA-256
`6506060f3f928e31abcbcfe46792ff4e0ae5c60bd9ad40964933c37ac854a9ea`.
Verification and replay apply to this preserved copy. A later SEC download
added a 105-byte script element and otherwise matched this copy byte for byte.
[Direct SEC acquisition](SEC_ACQUISITION.md)
[SEC filing index](https://www.sec.gov/Archives/edgar/data/789019/000095017023035122/0000950170-23-035122-index.htm)
[Preserved copy](originals/msft-20230630.htm.gz)

```powershell
uv run --locked --offline mypy
uv run --locked --offline pytest tests/test_verification_workflow.py tests/test_revenue_workflow.py -q
uv run --locked --offline pytest -q
uv run --locked --offline python artifacts/phase01/replay.py --microsoft
npm.cmd --prefix web run build
uv run --locked --offline --with playwright python artifacts/phase01/browser-replay.py
```

The CLI replay forbids socket operations, reingests identical bytes, removes the
initial input, and inspects the saved source. Synthetic perturbations exercise
the same reference checks and report their results in `reference_status`. Their
facts remain provisional.
[Validation output](verification-validation.txt)
