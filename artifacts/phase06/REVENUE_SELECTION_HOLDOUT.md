# SEC extraction holdout custody

Issue #59 reserves five domestic 10-K primary documents from five issuer
families, plus one synthetic document. Four filings supply 12 reviewed annual
observations across three statement layouts. The layouts vary in title and
units placement, fiscal-year labels, shared end dates, and week counts. The
target rows use four visible labels. The review marks distractors such as
segment revenue, subtotals in a consolidated statement, and the same company
total in notes or MD&A. Two inputs have no eligible target in the supplied
HTML. In one, Item 8 incorporates a separate exhibit. In the synthetic
document, the consolidated statement omits revenue and a division note
contains a plausible total. [Issue #59](https://github.com/kcinimod/frag/issues/59)

The reviewer opened original byte excerpts to establish the statement, row,
physical value and fiscal-period cells, scale, currency, consolidated scope,
and applicable disclosures. The review used the original Inline XBRL contexts
and units and corroborated amounts and full dates independently against SEC
Company Facts by accession. A repeated EDGAR transfer matched every primary
document byte for byte. The scoring archive preserves the reviewed spans,
layout signatures, distractors, absence evidence, and corroborating records.

The preparation audit compared issuer names and aliases, CIKs, annual-report
and amendment accessions, and original hashes against 30 issuer families and
35 distinct development or previously reserved originals. The inventory
covers the earlier development originals and the #24, #32, #43 and #54
cohorts, including the opened #54 inputs used in #56–#58. The scorer archive
preserves the inventory and its source hashes, SEC submission indexes, and
lineage evidence. The preparation overlap count is zero.
[Public custody receipt](revenue-selection-holdout-receipt.json)

## Verify and release

The two archives are held in `../FRAG-SEC-Holdout-59`. The runner archive has
only the original inputs and their manifest. The scoring archive holds the
references and evidence, including the incorporated exhibit. Run this check
from the repository root in scorer custody. It verifies the seals, opens the
reviewed byte ranges, corroborates the observations, and checks the
preparation inventory without loading model weights.

```powershell
.venv/Scripts/python.exe artifacts/phase06/revenue_selection_holdout.py '../FRAG-SEC-Holdout-59'
```

Before any selector receives the runner archive, assemble the final development
inventory from the frozen candidate. Preserve the preparation inventory entries
and add every development original or issuer lineage introduced since then.
Use JSON with a `sources` array. Each entry supplies `cik`, `accession`,
`issuer`, and the uncompressed original's `sha256`. Include `related_ciks`,
`aliases`, and `related_accessions` where applicable. Supply additional
manifest files by repeating `--final-inventory`. Record their printed hashes
and the successful recheck in the acceptance freeze alongside the production
and evaluation revisions, batching, runtime, and scoring rules.

```powershell
$custody = '../FRAG-SEC-Holdout-59'
$finalInventory = Join-Path $custody 'scorer/final-development-inventory.json'
.venv/Scripts/python.exe artifacts/phase06/revenue_selection_holdout.py $custody --final-inventory $finalInventory
```

After the freeze, provide only `runner/inputs.zip` to the isolated runner.
Keep the scorer archive, review labels, and original target locators in scorer
custody. The #56–#58 commands pin the opened #54 cohort. The held-out
comparison needs to bind to the #59 seals and score both absent-target controls.
[Comparison specification](https://github.com/kcinimod/frag/issues/55)
