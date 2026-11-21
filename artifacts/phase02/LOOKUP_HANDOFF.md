# Local annual revenue lookup

The pinned local model proposed a valid lookup for each retained Microsoft
fiscal year. The CLI and Chrome returned **USD 198,270,000,000 for FY2022**
and **USD 211,915,000,000 for FY2023**. Chrome opened both revenue cells as
text from the preserved FY2023 10-K after the input file had been removed.
The calculator still returned 6.88% in the browser replay.
[Issue #10](https://github.com/kcinimod/frag/issues/10)
[Owner review of the calculator](https://github.com/kcinimod/frag/issues/9#issuecomment-7061708387)

The lookups used source SHA-256
`6506060f3f928e31abcbcfe46792ff4e0ae5c60bd9ad40964933c37ac854a9ea`,
parser `annual-revenue-v4`, and evidence reference
`microsoft-fy2023-revenue-v2`. Each explicit run contains the resolved
request, exact evidence and request payload, model settings, raw proposal,
validation status, deterministic trace, and timings.
[Cold FY2023](lookup-validation/cold.json)
[Warm FY2023](lookup-validation/warm.json)
[Warm FY2022](lookup-validation/prior.json)

## Pinned local setup

- Runtime is llama.cpp Windows x64 CPU release `b6500`, fingerprint
  `b6500-a7a98e0f`, under the MIT license.
  [Release](https://github.com/ggml-org/llama.cpp/releases/tag/b6500)
  [License](https://github.com/ggml-org/llama.cpp/blob/b6500/LICENSE)
- Weights are Qwen2.5-0.5B-Instruct GGUF, quantized Q4_K_M at revision
  `9217f5db79a29953eb74d5343926648285ec7e67`, under Apache 2.0.
  [Weights and upstream digest](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/blob/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf)
  [License](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/blob/9217f5db79a29953eb74d5343926648285ec7e67/LICENSE)

The setup script checks the archive and weights against their upstream
SHA-256 digests. The launcher checks the weights again before starting.
Inference uses a single-slot runtime with a 4,096-token
context, four CPU threads, zero GPU layers, and runtime logging disabled.
FRAG issues one request over IPv4 loopback, with prompt caching disabled.
[Setup script](../../scripts/setup-local-model.ps1)
[Launcher](../../scripts/start-local-model.ps1)

## Windows acceptance run

From the repository root in Windows PowerShell after the README dependency
setup, run the setup script, then measure with the cached runtime and
weights. The measurement script creates a fresh ignored store, runs llama.cpp
with `--offline`, saves explicit runs, stops its server, and replays the cold
record. Its output names the run directory. The three retained JSON files
above came from the run below.

```powershell
.\scripts\setup-local-model.ps1
.\artifacts\phase02\measure-lookup.ps1
```

Measured on Windows laptop model 83VK with an Intel Core Ultra 7 251HX,
32 GiB installed RAM, and an NVIDIA RTX 5060 Laptop GPU with 8,151 MiB.
Starting the model, including verifying the weights, took 1,135 ms to reach
the health endpoint. The first CLI answer arrived 3,776 ms after the
launcher started. The run used the existing OS file cache.

| Request | CLI wall time | Planner wall time | Runtime peak working set through request |
| --- | ---: | ---: | ---: |
| FY2023, first request | 2,640 ms | 2,428 ms | 546.3 MiB |
| FY2023, model resident | 2,635 ms | 2,475 ms | 546.4 MiB |
| FY2022, model resident | 2,460 ms | 2,303 ms | 546.4 MiB |

Windows reported these peak working sets for the llama.cpp process. Across
nine one-second samples of Windows GPU process counters, the runtime PID
had no dedicated GPU usage entry, for a sampled peak of 0 MiB. This is the
CPU build with zero GPU layers. Each row represents one measured request.

The retained cold proposal replayed as `answered` with the same verified
FY2023 amount after the model stopped. To reproduce, use the store created
by the measurement script and the checked-in record.

```powershell
$run = Get-ChildItem .frag-model -Directory -Filter 'lookup-*' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
.venv/Scripts/frag.exe replay-lookup artifacts/phase02/lookup-validation/cold.json --store (Join-Path $run.FullName 'store')
```

For the Chrome replay, start the planner using the offline command in the
README. In a second PowerShell window, run these commands.

```powershell
npm.cmd --prefix web run build
uv run --locked --offline --with playwright python artifacts/phase01/browser-replay.py --lookup
```

Chrome passed clarification, both amount checks, and both original cell
links. The harness restricted browser traffic to the workspace origin
and Python networking to loopback. The lookup regression suite also
exercised wrong-year, unknown-ID, unsupported-operation, duplicate-key,
provisional evidence, unavailable model, and timeout outcomes. Saved-plan
replay passed with every Python socket operation disabled.
[Lookup regressions](../../tests/test_lookup_workflow.py)

```powershell
uv run --locked --offline pytest -q tests/test_lookup_workflow.py
uv run --locked --offline pytest -q
uv run --locked --offline mypy
```

All 15 lookup tests and all 74 project tests passed. Strict typechecking
and the frontend production build also passed.

## Scope

The question resolver handles documented single-year revenue phrases, and
coverage depends on the selected filing's verified evidence. Ambiguous or
unsupported phrasing asks for clarification. Lookup uses a 30-second
planner socket timeout and one attempt. The retained record identifies the
expected launcher configuration and stores the exact inference request.
Explicit records with a saved proposal can be replayed. Browser questions
stay in memory, and the CLI reads questions from its input prompt unless
given a positional argument. The CLI creates a record only with `--record`.
Growth questions in the chatbot belong to the next ticket.
