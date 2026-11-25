# GE, Home Depot, and UPS revenue

The shared filing workflow matched all ten reviewed observations to the
original statement, visible annual period, revenue cell, currency, and scale.
Nine observations from the current filings passed inline XBRL and disclosure
verification. The reviewed historical GE observation remains provisional.
[Issue #39](https://github.com/kcinimod/frag/issues/39) ·
[Independent review references](../../tests/fixtures/phase06_ge_hd_ups_review.json) ·
[Original custody](../phase05/SEC_HOLDOUT.md)

| FY2024 filing | FY2022 (USD millions) | FY2023 (USD millions) | FY2024 (USD millions) | FY2023 to FY2024 |
| --- | ---: | ---: | ---: | ---: |
| GE | 29,139 | 35,348 | 38,702 | 9.49% |
| Home Depot | 157,403 | 152,669 | 159,514 | 4.48% |
| UPS | 100,338 | 90,958 | 91,070 | 0.12% |

GE's growth uses the continuing-operations basis presented retrospectively
in the 2024 filing. Home Depot's FY2024 ended February 2, 2025, and includes
53 weeks and SRS results from acquisition. Its FY2023 has 52 weeks. An
equal-length request retains both cited operands and withholds the percentage.
UPS's as-reported comparison includes the effect of the Coyote divestiture.
The historical GE source shows FY2018 revenue of USD 121,615 million during
inspection. Asking for that year reports the missing inline XBRL evidence.

The pinned Phase 6 Qwen2.5-0.5B development model returned valid plans for all
six numeric questions. Both evidence gaps resolved before planning. All eight
responses and 42 original citation responses reproduced exactly with sockets
blocked after fresh ingestion. The record covers a single run of issue #39's
cases with one model process.
[Saved settings, plans, traces, and original citations](ge-hd-ups-validation.json.gz)

From the repository root in PowerShell, verify the reviewed observations,
exercise the browser API and CLI, and replay the retained model results.

```powershell
New-Item -ItemType Directory -Force -Path build | Out-Null
$issue39Tests = "build/issue39-tests-$([guid]::NewGuid().ToString('N'))"
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp $issue39Tests tests/test_opened_revenue.py tests/test_cisco_revenue.py tests/test_shared_year_revenue.py tests/test_development_revenue.py
.venv/Scripts/python.exe artifacts/phase06/replay_opened_revenue.py "build/issue39-replay-$([guid]::NewGuid().ToString('N'))"
```

For a browser review, unpack the originals and upload a file with
**Local original** selected. Open its filing detail and use **Ask the filing**
with the questions from the independent review references. The current filings
show a revenue lookup or growth result with links to the original excerpts.
The historical filing shows a **Provisional** FY2018 observation in its
filing detail and an evidence gap in the chat.

```powershell
$issue39Review = "build/issue39-review-$([guid]::NewGuid().ToString('N'))"
.venv/Scripts/python.exe -c "import gzip, pathlib, sys; out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True); src = pathlib.Path('artifacts/phase06/originals'); [(out / name).write_bytes(gzip.decompress((src / (name + '.gz')).read_bytes())) for name in ('ge-20241231.htm', 'hd-20250202.htm', 'ups-20241231.htm', 'ge10-k2018.htm')]" $issue39Review
Get-ChildItem -LiteralPath $issue39Review
```
