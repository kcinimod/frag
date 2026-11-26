# Target reported consolidated revenue

Target's FY2023 Form 10-K verifies all three annual observations in
the `Total revenue` row of its Consolidated Statements of Operations.
The visible fiscal-year labels and USD millions agree with the undimensioned
inline XBRL facts. Note 1 establishes consolidation and the fiscal calendar.
Note 3 supports the inclusion of merchandise and other revenue in the total.
[Issue #48](https://github.com/kcinimod/frag/issues/48) ·
[Independent review](../../tests/fixtures/phase06_target_review.json) ·
[Preserved original](originals/tgt-20240203.htm.gz) ·
[SEC filing](https://www.sec.gov/Archives/edgar/data/27419/000002741924000032/tgt-20240203.htm)

| Fiscal year | Original period | Weeks | Reported consolidated revenue (USD) |
| --- | --- | ---: | ---: |
| FY2021 | 2021-01-31 to 2022-01-29 | 52 | 106,005,000,000 |
| FY2022 | 2022-01-30 to 2023-01-28 | 52 | 109,120,000,000 |
| FY2023 | 2023-01-29 to 2024-02-03 | 53 | 107,412,000,000 |

The public filing workflow returned FY2023 revenue of $107,412,000,000
and reported FY2022 to FY2023 growth of -1.57%. The trace subtracts
$109,120,000,000 from $107,412,000,000, divides the resulting
-$1,708,000,000 by the FY2022 amount, and converts the ratio to a
percentage. The growth answer cites Note 1 for the 52- and 53-week periods.
The equal-length request withholds the percentage and cites both verified
amounts and the same original calendar disclosure.

The pinned Qwen2.5-0.5B Q4_K_M planner produced the lookup and reported growth
plans. The equal-length request resolved before planning. Fresh intake and
socket-blocked replay reproduced all three results and 14 citation responses.
The case scorer credited two supported answers and one grounded abstention,
with zero findings. [Saved run and replay](target-validation.json.gz)

Chrome 158.0.8127.37 verified the local upload, all three visible results,
and all 14 citation tabs using the saved plans and local-only browser requests.

## Reproduce in PowerShell

Run the focused checks from the repository root.

```powershell
New-Item -ItemType Directory -Force -Path build | Out-Null
$targetTests = "build/target-tests-$([guid]::NewGuid().ToString('N'))"
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp $targetTests tests/test_target_revenue.py
```

Replay the saved plans and compare each result and citation response.

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
run = json.loads(gzip.decompress((phase / "target-validation.json.gz").read_bytes()))
work = Path("build") / f"target-replay-{uuid4().hex}"
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
$targetOriginal = "build/target-$([guid]::NewGuid().ToString('N')).htm"
.venv/Scripts/python.exe -c "import gzip, pathlib, sys; pathlib.Path(sys.argv[1]).write_bytes(gzip.decompress(pathlib.Path('artifacts/phase06/originals/tgt-20240203.htm.gz').read_bytes()))" $targetOriginal
Get-Item -LiteralPath $targetOriginal
```

Upload the HTML in the filing workspace with **Local original** selected.
A running local planner supports the first two questions.

| Question in **Ask the filing** | Expected result |
| --- | --- |
| What was reported consolidated revenue in FY2023? | USD 107,412,000,000 with the original statement and applicable notes. |
| What was reported consolidated revenue growth from FY2022 to FY2023 as reported? | -1.57% with the subtraction, division, and percentage steps and the 52- versus 53-week caveat. |
| What was reported consolidated revenue growth from FY2022 to FY2023? Compare equal-length fiscal periods only. | Growth is withheld. **Supported observations** shows $109,120,000,000 for FY2022 and $107,412,000,000 for FY2023. Open the evidence links for both amounts and the Note 1 fiscal calendar. |
