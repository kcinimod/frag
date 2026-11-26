# Netflix reported consolidated revenue

The FY2024 Netflix 10-K verifies all three annual observations against the
statement, inline XBRL, and applicable disclosures. The statement reports
USD in thousands. Note 1 establishes the consolidation scope and explains
the recognition of monthly membership fees and the treatment of member
taxes. The revenue policy citation spans the original page break.
[Issue #47](https://github.com/kcinimod/frag/issues/47) ·
[Independent review](../../tests/fixtures/phase06_netflix_review.json) ·
[Original 10-K](originals/nflx-20241231.htm.gz)

| Fiscal year | Reported consolidated revenue (USD) |
| --- | ---: |
| FY2022 | 31,615,550,000 |
| FY2023 | 33,723,297,000 |
| FY2024 | 39,000,966,000 |

The public filing workflow returned FY2024 revenue of $39,000,966,000
and FY2023 to FY2024 reported growth of 15.65%. The growth trace subtracts
the prior revenue to get $5,277,669,000, divides by $33,723,297,000, and
converts the result to a percentage. The FY2021 to FY2024 request withheld
the percentage and cited the complete FY2022, FY2023, and FY2024 statement
inventory alongside the verified FY2024 observation and its citations.

The pinned Qwen2.5-0.5B Q4_K_M model produced the lookup and growth plans.
The missing-year request resolved before planning. After the server stopped,
fresh intake and socket-blocked replay matched all three results and their
11 original citation responses. [Saved run and replay](netflix-validation.json.gz)

## Reproduce in PowerShell

Run the seven focused checks from the repository root. The checks cover
original evidence locators, the public browser API, and CLI replay with
sockets blocked.

```powershell
New-Item -ItemType Directory -Force -Path build | Out-Null
$issue47Tests = "build/issue47-test-$([guid]::NewGuid().ToString('N'))"
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp $issue47Tests tests/test_netflix_revenue.py
```

Replay the saved local-model plans from a fresh store with sockets blocked.
Each case should print `matched` after checking both the result and opened
original excerpts.

```powershell
@'
import gzip
import json
import socket
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, "artifacts/phase04")
from sec_holdout_runner import ingest, replay_case

def deny_network(*args, **kwargs):
    raise AssertionError("Offline replay opened a socket")

socket.socket = socket.create_connection = socket.getaddrinfo = deny_network
phase = Path("artifacts/phase06")
run = json.loads(gzip.decompress((phase / "netflix-validation.json.gz").read_bytes()))
work = Path("build") / f"issue47-replay-{uuid4().hex}"
work.mkdir(parents=True)
original = work / run["source"]["original_filename"]
original.write_bytes(gzip.decompress((phase / "originals" / (original.name + ".gz")).read_bytes()))
store = work / "store"
source = ingest(store, original, run["source"])
original.unlink()
for case_id, row in run["cases"].items():
    case = {"case_id": case_id, "question": row["question"]}
    replay = replay_case(store, case, source, row["live"])
    assert replay == {"status": "matched"}, replay
    print(case_id, replay["status"])
'@ | .venv/Scripts/python.exe -
```

Unpack the preserved filing for browser review.

```powershell
New-Item -ItemType Directory -Force -Path build | Out-Null
$issue47Original = "build/issue47-nflx-$([guid]::NewGuid().ToString('N')).htm"
.venv/Scripts/python.exe -c "import gzip, pathlib, sys; pathlib.Path(sys.argv[1]).write_bytes(gzip.decompress(pathlib.Path('artifacts/phase06/originals/nflx-20241231.htm.gz').read_bytes()))" $issue47Original
Get-Item -LiteralPath $issue47Original
```

In the filing workspace, upload that HTML with **Local original**
selected. A running local planner supports the first two questions.

| Question in **Ask the filing** | Expected result |
| --- | --- |
| What was reported consolidated revenue in FY2024? | $39,000,966,000 with original statement and policy citations. |
| What was reported consolidated revenue growth from FY2023 to FY2024 as reported? | 15.65% with both operands and the subtraction, division, and percentage steps. |
| What was reported consolidated revenue growth from FY2021 to FY2024? | Growth withheld. **Supported observations** contains the FY2024 amount. The statement period link opens the FY2022 to FY2024 headers and the FY2024 evidence link opens the reported revenue. |
