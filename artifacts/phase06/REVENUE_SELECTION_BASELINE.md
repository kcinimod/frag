# Rules-alone SEC revenue extraction

The rules shortlisted and selected the independently reviewed table and row
in **7 of 7 filings**. The shared extractor matched **12 of 21 annual
observations** exactly. All 12 remain provisional under the filing verification
policy. The extractor emitted zero verified observations.
[Issue #56](https://github.com/kcinimod/frag/issues/56) · [Run record](revenue-selection-baseline/run.json) · [Independent score](revenue-selection-baseline/score.json)

| Filing | Visible tables | Selected row | Exact observations | First stop |
| --- | ---: | --- | ---: | --- |
| Mastercard FY2024 | 120 | `table-56/row-6` | 3/3 | Statement issuer verification, supplied company conflict, and applicable disclosures |
| Oracle FY2024 | 81 | `table-36/row-9` | 3/3 | Statement issuer verification and applicable disclosures |
| PepsiCo FY2024 | 115 | `table-28/row-3` | 0/3 | The extractor expects a shared fiscal year-end above the revenue row. The filing lists three different fiscal year-ends in the preamble. |
| Adobe FY2017 | 201 | `table-121/row-9` | 0/3 | The extractor retained three displayed amounts with unknown period starts. The preserved original lacks inline XBRL corroboration. |
| Adobe FY2024 | 78 | `table-32/row-8` | 0/3 | The extractor retained three displayed amounts with unknown period starts and flagged an inline XBRL concept conflict. |
| eBay FY2024 | 97 | `table-31/row-5` | 3/3 | Applicable disclosures |
| Salesforce FY2024 | 81 | `table-31/row-7` | 3/3 | Applicable disclosures |

The inventory contains 773 tables before financial shortlisting. It records
stable IDs scoped to the original hash, markup IDs when present, nearby text,
captions, the physical cells and their grid positions and spans, original
locators, and inline facts with their context and unit definitions. Fiscal headers and unit declarations retain their
placement in cells or surrounding text. For unsupported geometry the record
keeps the original physical cells and an explicit grid error. Visibility
follows the original markup, including explicit hidden elements and inline
styles. Each gzip file in the run directory is named by filing accession and
bound to its SHA-256 in the run record.

The score uses the sealed independent review after the rules run. It checks
the selected IDs against reviewed original table and revenue row spans, then
checks the amount, full period, currency, scale, scope, and original period,
amount, and unit anchors. The archived #45 result remains the historical
acceptance checkpoint. [Issue #45 acceptance](CONTINUATION_ACCEPTANCE.md)

The run records parse, inventory serialization, and combined selection and
validation times per filing. The Windows process peak working set was about
118 MiB for the run, including inventory serialization. The per-filing
working-set fields are cumulative process peaks at the end of each filing.
The run made zero model calls. Device VRAM was unmeasured.

The offline rerun reproduced all seven inventory files byte for byte and
matched the retained selections, observations, and scores. Code and dependency
hashes normalize Windows CRLF line endings.

Labeled synthetic originals show that the rules select a consolidated row in
the presence of segment revenue, report `no_candidate` when the consolidated
row is absent, and report `ambiguous_candidates` when two statements qualify.
Submitting a segment row or a subtotal alongside an explicit total directly
to the shared extractor yields `unsupported_scope` and no observations.
[Synthetic regression checks](../../tests/test_revenue_selection.py)
