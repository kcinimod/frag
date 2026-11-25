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

The seven earlier development originals and Cisco retained the same facts,
statement periods, diagnostics, and comparison evidence as the pre-change
revision. The regression suite also checks Walmart's total revenue separately
from its net sales subtotal.

The four lookup and growth questions were answered using the Phase 6
baseline model, runtime, and generation settings. All four saved results
and their citation responses matched offline, including 16 opened
citations. This run measures issue #38's two filings.
[Saved plans, traces, citations, and replay results](pg-ko-validation.json.gz)

From the repository root in PowerShell, the regression checks verify original
evidence spans, exercise the browser API and CLI, and replay saved plans
with sockets blocked.

```powershell
New-Item -ItemType Directory -Force -Path build | Out-Null
$issue38Tests = "build/phase06-test-$([guid]::NewGuid().ToString('N'))"
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp $issue38Tests tests/test_shared_year_revenue.py tests/test_cisco_revenue.py
```

To open the two originals in the browser, unpack them into a fresh directory.
Upload either HTML file with **Local original** selected, then use
**Ask the filing**. Both years and the disclosure excerpts are available
from the growth result's citation links.

```powershell
$issue38Review = "build/phase06-review-$([guid]::NewGuid().ToString('N'))"
.venv/Scripts/python.exe -c "import gzip, pathlib, sys; out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True); src = pathlib.Path('artifacts/phase06/originals'); [(out / name).write_bytes(gzip.decompress((src / (name + '.gz')).read_bytes())) for name in ('pg-20240630.htm', 'ko-20241231.htm')]" $issue38Review
Get-ChildItem -LiteralPath $issue38Review
```

To reproduce the retained local-model plans from fresh ingestion with
sockets blocked, run the following from the repository root. Each of the
four questions should print `matched`.

```powershell
@'
import gzip
import json
import socket
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, 'artifacts/phase04')
from sec_holdout_runner import ingest, replay_case

def deny(*args, **kwargs):
    raise AssertionError('Socket opened during replay')

socket.socket = deny
phase = Path('artifacts/phase06')
records = json.loads(gzip.decompress((phase / 'pg-ko-validation.json.gz').read_bytes()))
refs = json.loads(Path('tests/fixtures/phase06_pg_ko_review.json').read_bytes())
work = Path('build') / f'issue38-replay-{uuid4().hex}'
work.mkdir(parents=True)
store = work / 'store'
for filename, ref in refs.items():
    original = work / filename
    original.write_bytes(gzip.decompress((phase / 'originals' / (filename + '.gz')).read_bytes()))
    source = ingest(store, original, ref['source'])
    original.unlink()
    for case in ref['cases']:
        key = filename + '-' + case['kind']
        row = records[key]
        replay = replay_case(store, {'case_id': key, 'question': row['question']}, source, row['live'])
        assert replay == {'status': 'matched'}, key
        print(key, 'matched')
'@ | .venv/Scripts/python.exe -
```
