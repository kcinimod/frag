# Filing chatbot growth acceptance

The local planner proposed a valid three-step program for “How did reported
consolidated revenue change from FY2022 to FY2023?” The calculator used the
retained Microsoft FY2023 10-K and returned **6.88%**. It subtracted USD
198,270,000,000 from USD 211,915,000,000, divided USD 13,645,000,000 by the
FY2022 amount, and converted the resulting ratio of 2729/39654 to a percent.
The answer cites both original revenue cells, four applicable notes, and
three comparison disclosures. The caveats describe acquisition and currency
effects on reported consolidated revenue.

The run used source SHA-256
`6506060f3f928e31abcbcfe46792ff4e0ae5c60bd9ad40964933c37ac854a9ea`,
parser `annual-revenue-v4`, and evidence reference `microsoft-fy2023-revenue-v2`.
Both records include the exact evidence, model request, proposed plan,
validation status, calculation trace, and timings.
[Issue #11](https://github.com/kcinimod/frag/issues/11) ·
[Cold record](chat-growth-validation/cold.json) ·
[Warm record](chat-growth-validation/warm.json)

## Measured Windows run

The measured configuration was llama.cpp Windows x64 CPU `b6500-a7a98e0f`
with the checked-in Qwen2.5-0.5B-Instruct Q4_K_M at weights revision
`9217f5db79a29953eb74d5343926648285ec7e67`, four CPU threads,
4,096 context tokens, and zero GPU layers. A separate run with the
Qwen2.5-1.5B-Instruct Q4_K_M working-tree configuration also returned 6.88%
on both requests and replayed successfully after its process exited.
[Model setup and pins](LOOKUP_HANDOFF.md)

The Windows laptop has an Intel Core Ultra 7 251HX, 32 GiB installed RAM,
and an NVIDIA RTX 5060 Laptop GPU. The first answer arrived 5.22 seconds
after starting the launcher, including 0.83 seconds for checksum verification
and startup. The model process started fresh with the existing Windows file
cache. Each row represents one request.

| Request | CLI wall time | Planner wall time | Runtime peak working set |
| --- | ---: | ---: | ---: |
| Cold | 4.39 s | 4.17 s | 573.94 MiB |
| Warm | 4.32 s | 4.17 s | 574.02 MiB |

Across 10 Windows GPU counter samples, Windows reported no dedicated GPU
memory entries for the CPU runtime PID. The measurement records 0 MiB and
zero matching PID samples. The script waited for its model process to exit
and verified that the cold record replayed to identical CLI output.
The measurement port was 8088 because a separate local planner was using
8087. The replay test also disables all Python socket operations.
[Measurement record](chat-growth-validation/measurement.json) ·
[Growth regression tests](../../tests/test_chat_growth.py)

## Windows PowerShell reproduction

From the repository root with dependencies and the pinned model already
cached, run the measurement script on an unused loopback port. The script
ingests the retained source into a fresh store and writes the cold and warm
records under the reported run directory. Replay the checked-in cold plan
against the store created by the measurement.

```powershell
$measurement = .\artifacts\phase02\measure-lookup.ps1 -Growth -Port 8088 | ConvertFrom-Json
$store = Join-Path (Join-Path '.frag-model' $measurement.run) 'store'
.venv/Scripts/frag.exe replay-ask artifacts/phase02/chat-growth-validation/cold.json --store $store
```

For the browser replay, start the offline planner on its standard port using
the README command. In a second PowerShell window, run the build and replay.
The Chrome run used the 1.5B configuration and checked clarification, 6.88%,
the operation trace, the caveat, and navigation to both original cells and
the comparison disclosure after the upload file was removed. The harness
restricted traffic to loopback.

```powershell
npm.cmd --prefix web run build
uv run --locked --offline --with playwright python artifacts/phase01/browser-replay.py --chat-growth
uv run --locked --offline pytest -q tests/test_chat_growth.py tests/test_lookup_workflow.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m mypy
```

Controlled proposals rejected a current-year denominator, an unknown fact
ID, an unsupported operation, reversed subtraction, a forward step
reference, and invalid arity. The tests also checked ineligible guidance
and provisional evidence, plus an unresolved comparison.

The chatbot supports the README's question forms for one selected filing.
Growth requests require two explicit fiscal years in chronological order
and a compatible verified comparative pair. Ordinary browser requests have
no persistent history. The planner makes one attempt with a 30-second
socket timeout. The calculator remains available independently.
