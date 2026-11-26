# NVIDIA reported consolidated revenue

The FY2025 Form 10-K's consolidated income statement and inline XBRL agree
on all three annual observations. Note 1 establishes the fiscal calendar,
consolidation, revenue recognition, and comparative presentation.
[Issue #49](https://github.com/kcinimod/frag/issues/49) ·
[Independent review](../../tests/fixtures/phase06_nvidia_review.json) ·
[FY2025 original](originals/nvda-20250126.htm.gz) ·
[FY2018 original](originals/nvda-2018x10k.htm.gz)

| Fiscal year | Annual period | Verified reported consolidated revenue (USD) |
| --- | --- | ---: |
| FY2023 | 2022-01-31 to 2023-01-29 | 26,974,000,000 |
| FY2024 | 2023-01-30 to 2024-01-28 | 60,922,000,000 |
| FY2025 | 2024-01-29 to 2025-01-26 | 130,497,000,000 |

The filing workflow reports **$130.497 billion** for FY2025 and **114.20%**
reported growth from FY2024 to FY2025. The trace subtracts $60.922 billion
from $130.497 billion, divides the $69.575 billion difference by $60.922
billion, and converts the ratio to a percentage.

The FY2018 original preserves three provisional observations for FY2016
through FY2018. The statement shows the FY2018 revenue cell, and the
original lacks the inline XBRL fact, context, and unit needed to verify it.
The filing answer withholds the numeric result.

The pinned Qwen2.5-0.5B Q4_K_M planner supplied both numeric plans. The
historical evidence gap resolved before planning. The opened-cohort
scorer matched all six observations, credited both numeric answers and
the historical abstention, and recorded zero findings. Fresh intake and
socket-blocked replay reproduced all three results and 11 original
citation responses. [Saved results, scores, and citations](nvidia-validation.json.gz)

## Reproduce in PowerShell

Run the focused tests from the repository root.

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp "build/nvidia-tests-$([guid]::NewGuid().ToString('N'))" tests/test_nvidia_revenue.py
```

Replay the recorded plans and the FY2018 evidence gap with sockets blocked.

```powershell
@'
import gzip
import json
from pathlib import Path
import socket
import sys
from uuid import uuid4

sys.path.insert(0, "artifacts/phase04")
from sec_holdout_runner import ingest, replay_case

def deny_network(*args, **kwargs):
    raise AssertionError("Offline replay opened a socket")

socket.socket = socket.create_connection = socket.getaddrinfo = deny_network
phase = Path("artifacts/phase06")
run = json.loads(gzip.decompress((phase / "nvidia-validation.json.gz").read_bytes()))
work = Path("build") / f"nvidia-replay-{uuid4().hex}"
work.mkdir(parents=True)
sources = {}
for filename, entry in run["sources"].items():
    original = work / filename
    original.write_bytes(gzip.decompress((phase / "originals" / (filename + ".gz")).read_bytes()))
    sources[filename] = ingest(work / "store", original, entry["metadata"])
    original.unlink()
for case_id, row in run["cases"].items():
    source = sources[row["filename"]]
    replay = replay_case(work / "store", {"case_id": case_id, "question": row["question"]}, source, row["live"])
    assert replay == {"status": "matched"}, replay
    print(case_id, replay["status"])
'@ | .venv/Scripts/python.exe -
```

For browser review, unpack both originals.

```powershell
$nvidiaOriginals = "build/nvidia-originals-$([guid]::NewGuid().ToString('N'))"
.venv/Scripts/python.exe -c "import gzip, pathlib, sys; out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True); files = pathlib.Path('artifacts/phase06/originals').glob('nvda-*.htm.gz'); [(out / path.stem).write_bytes(gzip.decompress(path.read_bytes())) for path in files]" $nvidiaOriginals
Get-ChildItem -LiteralPath $nvidiaOriginals
```

Upload the corresponding HTML in the filing workspace with **Local original**
selected. Use the running local planner for the two questions on the recent filing.

| Filing | Question in **Ask the filing** | Expected result |
| --- | --- | --- |
| `nvda-20250126.htm` | What was reported consolidated revenue in FY2025? | USD 130,497,000,000 with links to the original statement and Note 1. |
| `nvda-20250126.htm` | What was reported consolidated revenue growth from FY2024 to FY2025 as reported? | 114.20% with the subtraction, division, and percentage steps. Open both operand citations and the Note 1 links. |
| `nvda-2018x10k.htm` | What was reported consolidated revenue in FY2018? | An evidence gap explaining that the original lacks the required inline XBRL fact, context, and unit. The answer contains no amount. |
