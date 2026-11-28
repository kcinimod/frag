# Fresh four-issuer extraction check

The revised rules matched **0 of 12** observations on four fresh issuer
families. The frozen baseline also matched **0 of 12**. All four expected
rows were in the parsed inventories. The result leaves the browser and CLI
integration gate unmet.

| Issuer | Reviewed consolidated label | Baseline exact | Revised exact | Revised stop |
| --- | --- | ---: | ---: | --- |
| Dollar General | Net sales | 0/3 | 0/3 | Selected the correct row. The extractor did not establish the fiscal calendar for split date headers. |
| Johnson & Johnson | Sales to customers | 0/3 | 0/3 | The adjacent title combines issuer, statement heading, units, and a note reference. The heading check rejects it. The row meets the new inline evidence check. |
| Best Buy | Revenue | 0/3 | 0/3 | The heading matches. The intervening dollars-and-shares units block stops the heading search. |
| Macy's | Total revenue | 0/3 | 0/3 | The browser shows a multi-line heading and units block before the table. The shortlist has no statement heading, caption, or nearby text for that table. |

This check covers three annual observations per filing. It has four
target-present inputs and provides no new estimate of absent-target
abstention. The earlier opened-cohort results remain development evidence.
[Opened-cohort replay](REVENUE_EXTRACTION_FOLLOWUPS.md)

## Freeze and review

The freeze pins the two Git revisions, filing accessions, original HTML,
SEC submission metadata, and Company Facts snapshots. It used the first
non-amended 10-K filed in calendar 2025 from each of four prespecified
issuers. CIKs, issuer names, accessions and original HTML hashes have no
overlap with the #60 development inventory or the opened #59 cohort.

Before running either revision, I selected the consolidated rows and read
their fiscal columns in offline Chrome. I recorded the exact value-cell
origins using the inline XBRL element IDs, then checked all 12 periods and
normalized amounts against SEC Company Facts by accession. The review
uses Chrome and SEC records independently of FRAG's parser and extractor.
It was performed in this session.
[Freeze](revenue-extraction-fresh/freeze.json) ·
[Reviewed observations](revenue-extraction-fresh/review.json) ·
[SHA-256 receipt](revenue-extraction-fresh/receipt.json)

## Socket-blocked replay

The unchanged SEC inputs are saved locally under
`build/phase06-extraction-followups/fresh-sources`, in one directory per
CIK. The report commits the scores and review, and each replay checks the
local input hashes before extraction. Run from the repository root.

```powershell
$inputs = 'build/phase06-extraction-followups/fresh-sources'
$saved = 'artifacts/phase06/revenue-extraction-fresh'
foreach ($variant in @('baseline', 'candidate')) {
    $out = Join-Path 'build' ("fresh-extraction-$variant-" + [guid]::NewGuid() + '.json')
    .venv/Scripts/python.exe artifacts/phase06/revenue_extraction_fresh_replay.py $variant $inputs $out
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ((Get-FileHash $out).Hash -ne (Get-FileHash "$saved/$variant-score.json").Hash) {
        throw "Replay differs for $variant."
    }
}
```

Both replay files matched their saved hashes.
[Baseline results](revenue-extraction-fresh/baseline-score.json) ·
[Revised results](revenue-extraction-fresh/candidate-score.json)
