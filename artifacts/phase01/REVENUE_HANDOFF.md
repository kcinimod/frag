# Issue #3 provisional revenue handoff

This records the extraction checkpoint. The current fact statuses and replay
are described in the [issue #4 verification handoff](VERIFICATION_HANDOFF.md).

The SEC filing index identifies Microsoft Corporation (CIK 789019), accession
`0000950170-23-035122`, filed July 27, 2023, for the year ended June 30, 2023.
Direct requests from the run environment returned HTTP 403. A GET from the
EDGAR mirror returned 9,963,591 bytes, matching the primary HTML size in the
SEC filing index. The decompressed SHA-256 is
`6506060f3f928e31abcbcfe46792ff4e0ae5c60bd9ad40964933c37ac854a9ea`.
A direct EDGAR byte comparison remains open.
[EDGAR mirror](https://edgar-mirror.sec-api.io/789019/000095017023035122/msft-20230630.htm)
[SEC filing index](https://www.sec.gov/Archives/edgar/data/789019/000095017023035122/0000950170-23-035122-index.htm)
[Compressed original](originals/msft-20230630.htm.gz)

The source markup shows the Item 8 Income Statements heading above table 25.
The scale disclosure in row 2 specifies millions with a per-share exception.
Row 5 contains the June 30 annual header and merged year cells. The Total
revenue row is row 12. Its inline tags reference a USD unit and undimensioned
Microsoft contexts whose dates agree with the visible year headers.
[SEC statement](https://www.sec.gov/Archives/edgar/data/789019/000095017023035122/msft-20230630.htm)

| Period | Source cell | Raw amount | Normalized USD |
| --- | --- | ---: | ---: |
| July 1, 2021 through June 30, 2022 | Row 12, cell 8, line 4403 | 198,270 | 198,270,000,000 |
| July 1, 2022 through June 30, 2023 | Row 12, cell 4, line 4399 | 211,915 | 211,915,000,000 |

The recorded facts retain the original label, parser and source identifiers,
inline contexts, and one-based source coordinates. The replay blocks socket
operations in CLI processes, checks duplicate-free replay, removes the initial
input, and resolves value and year locators against the retained bytes.
[Manifest and facts](microsoft-revenue.json)

## Reproduce

```powershell
uv run --locked --offline mypy
uv run --locked --offline pytest tests/test_revenue_workflow.py -q
uv run --locked --offline pytest -q
npm.cmd --prefix web run build
uv run --locked --offline --with playwright python artifacts/phase01/browser-replay.py
uv run --locked --offline python artifacts/phase01/replay.py --microsoft
```

The run log records the test, build, and replay results.
[Validation output](revenue-validation.txt)

Both observations remain provisional. Phase 1 verification still needs
independent evidence records and bounded applicable notes for revenue
recognition, consolidation, recasts, acquisitions, and period comparability.
The repository's wider financial acceptance checklist remains open.
