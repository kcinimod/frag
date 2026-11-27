"""Run the Phase 6 model-only revenue selection experiment."""

import argparse
from dataclasses import asdict
import gzip
from hashlib import file_digest, sha256
import http.client
from io import BytesIO
import json
from pathlib import Path
import platform
from shutil import which
import subprocess
from time import monotonic, perf_counter, sleep
from typing import Any
from uuid import uuid4
from zipfile import ZipFile

from revenue_selection_baseline import PHASE, ROOT, elapsed, json_bytes, peak_working_set_bytes, read_sealed

from frag.revenue_model_selection import (
    PROMPT_BYTE_LIMIT, ROW_FRAGMENT_BYTES, SYSTEM_PROMPT, TABLE_CONTEXT_BYTES,
    InvalidModelResponse, ModelUnavailable, run_model_selection,
)
from frag.revenue_selection import filing_inventory
from frag.store import SourceMetadata

WEIGHTS = {
    "repository": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
    "revision": "91cad51170dc346986eccefdc2dd33a9da36ead9",
    "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "sha256": "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
    "alias": "frag-qwen25-15b-q4km",
    "quantization": "Q4_K_M",
}
RUNTIME_FINGERPRINT = "b6500-a7a98e0f"
CONTEXT_SIZE = 8192
MAX_RESPONSE_TOKENS = 64
TIMEOUT_SECONDS = 90
ROW_ID_GRAMMAR = r'''
root ::= "{" ws "\"row_id\"" ws ":" ws choice ws "}"
ws ::= [ ]?
'''.strip()
CONTROLS = {"absent": None, "distractor": "table-2/row-4"}


class LocalSelector:
    def __init__(self, port: int, alias: str) -> None:
        self.port = port
        self.alias = alias

    def request(self, path: str, payload: dict[str, Any] | None = None, *, timeout: int = TIMEOUT_SECONDS) -> Any:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            if payload is None:
                connection.request("GET", path)
            else:
                connection.request("POST", path, json.dumps(payload), {"Content-Type": "application/json"})
            response = connection.getresponse()
            body = response.read(65537)
            if response.status != 200:
                raise ModelUnavailable(f"HTTP {response.status}: {body[:512].decode(errors='replace')}")
        except (OSError, http.client.HTTPException) as error:
            raise ModelUnavailable(str(error)) from error
        finally:
            connection.close()
        try:
            if len(body) > 65536:
                raise ValueError("The local server exceeded the response size limit.")
            return json.loads(body)
        except (ValueError, RecursionError) as error:
            raise InvalidModelResponse(str(error)) from error

    def propose(self, prompt: str, row_ids: tuple[str, ...]) -> str:
        choices = ['"null"', *(json.dumps(json.dumps(row_id)) for row_id in row_ids)]
        grammar = ROW_ID_GRAMMAR + "\nchoice ::= " + " | ".join(choices)
        decoded = self.request("/v1/chat/completions", {
            "model": self.alias,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            "max_tokens": MAX_RESPONSE_TOKENS, "temperature": 0, "seed": 0, "grammar": grammar,
        })
        try:
            if decoded["model"] != self.alias or decoded["system_fingerprint"] != RUNTIME_FINGERPRINT:
                raise ModelUnavailable("The endpoint did not identify the pinned local model and runtime.")
            choice = decoded["choices"][0]
            proposal = choice["message"]["content"]
            if choice["finish_reason"] != "stop" or not isinstance(proposal, str):
                raise InvalidModelResponse("The model did not complete a text response.")
            return proposal
        except (KeyError, IndexError, TypeError) as error:
            raise InvalidModelResponse("The local server returned an invalid chat response.") from error

    def wait_ready(self, process: subprocess.Popen[bytes]) -> None:
        deadline = monotonic() + 60
        while process.poll() is None and monotonic() < deadline:
            try:
                if self.request("/health", timeout=2) == {"status": "ok"}:
                    models = self.request("/v1/models", timeout=2)
                    if [model["id"] for model in models["data"]] == [self.alias]:
                        return
            except (ModelUnavailable, InvalidModelResponse, KeyError, TypeError):
                pass
            sleep(0.25)
        raise RuntimeError("The local model did not start. Inspect llama-server.log in the staging directory.")


def digest(path: Path) -> str:
    with path.open("rb") as payload:
        return file_digest(payload, "sha256").hexdigest()


def model_peak_working_set(pid: int) -> int | None:
    if platform.system() != "Windows":
        return None
    measured = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", f"(Get-Process -Id {pid}).PeakWorkingSet64"],
        capture_output=True, text=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    value = measured.stdout.strip()
    return int(value) if value.isdecimal() else None


def nvidia_memory_sample() -> dict[str, int] | None:
    tool = which("nvidia-smi")
    if tool is None:
        return None
    measured = subprocess.run(
        [tool, "--query-gpu=name,memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    devices = {}
    for line in measured.stdout.splitlines():
        name, _, memory = line.rpartition(", ")
        if name and memory.isdecimal():
            devices[name] = int(memory)
    return devices or None


def filing_source(filing: dict[str, Any]) -> dict[str, Any]:
    metadata = SourceMetadata(
        company=filing["issuer"], accession=filing["accession"], form=filing["form"],
        filing_date=filing["filing_date"], source_url=filing["source_url"],
    )
    return {**asdict(metadata), "provenance": {"kind": "local_original"}}


def write_cases(
    runner_payload: bytes, staging: Path, selector: LocalSelector, pid: int, accelerated: bool,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    def run_case(original: bytes, source: dict[str, Any]) -> dict[str, Any]:
        start = perf_counter()
        inventory = filing_inventory(original)
        inventory_ms = elapsed(start)
        start = perf_counter()
        result = run_model_selection(inventory, source, selector.propose)
        return {
            **result, "original_sha256": inventory.original_sha256, "inventory_ms": inventory_ms,
            "selection_and_validation_ms": elapsed(start),
            "process_peak_working_set_bytes": peak_working_set_bytes(),
            "model_peak_working_set_bytes": model_peak_working_set(pid),
            "nvidia_device_memory_used_mib": nvidia_memory_sample() if accelerated else None,
        }

    controls = {}
    for label, expected_row in CONTROLS.items():
        path = ROOT / "tests" / "fixtures" / f"revenue-selection-{label}.html"
        source = asdict(SourceMetadata(company="Example Corporation"))
        result = run_case(path.read_bytes(), {**source, "provenance": {"kind": "synthetic"}})
        controls[label] = {**result, "fixture": path.relative_to(ROOT).as_posix(), "expected_row_id": expected_row}
        (staging / f"control-{label}.json").write_bytes(json_bytes(controls[label]))
        print(f"Control {label}: {result['stop']}", flush=True)
    results = {}
    with ZipFile(BytesIO(runner_payload)) as runner:
        manifest = json.loads(runner.read("manifest.json"))
        for filing in manifest["sources"]:
            source_id = filing["source_id"]
            original = runner.read(filing["path"])
            if len(original) != filing["byte_length"] or sha256(original).hexdigest() != filing["sha256"]:
                raise ValueError(f"Original differs from the #54 manifest for {source_id}.")
            print(f"Selecting {filing['issuer']} ({source_id})", flush=True)
            result = run_case(original, filing_source(filing))
            results[source_id] = {**result, "issuer": filing["issuer"]}
            (staging / f"{source_id}.json").write_bytes(json_bytes(results[source_id]))
            print(f"  {len(result['batches'])} batches, stop={result['stop']}, selected={result['selected']}", flush=True)
    return manifest["cohort"], results, controls


def run(
    runner_path: Path, output: Path, model_dir: Path, runtime: Path,
    port: int, gpu_layers: int, device: str | None,
) -> None:
    runner_payload = read_sealed(runner_path, "runner")
    if output.exists():
        raise FileExistsError(output)
    weights = (model_dir / WEIGHTS["filename"]).resolve()
    runtime = runtime.resolve()
    if digest(weights) != WEIGHTS["sha256"]:
        raise ValueError("The local GGUF did not match the pinned Qwen2.5 1.5B weights.")
    runtime_files = {path.name: digest(path) for path in [runtime, *sorted(runtime.parent.glob("*.dll"))]}
    dependencies = (
        "artifacts/phase06/revenue_selection_model.py", "artifacts/phase06/revenue_selection_baseline.py",
        "src/frag/revenue_model_selection.py", "src/frag/revenue_selection.py", "src/frag/income_html.py",
        "src/frag/dated_revenue.py", "src/frag/revenue.py", "src/frag/revenue_notes.py",
        "src/frag/apple-revenue-reference.json", "src/frag/store.py", "uv.lock",
    )
    code_hashes = {
        name: sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in dependencies
    }
    # A run-specific alias ties readiness and every decision to the process launched here.
    alias = f"{WEIGHTS['alias']}-{uuid4().hex}"
    arguments = [
        "--offline", "--host", "127.0.0.1", "--port", str(port), "--model", str(weights),
        "--alias", alias, "--ctx-size", str(CONTEXT_SIZE),
        "--threads", "4", "--threads-batch", "4", "--n-gpu-layers", str(gpu_layers), "--parallel", "1",
    ]
    if device is not None:
        arguments.extend(("--device", device))
    staging = output.with_name(f"{output.name}.incomplete-{uuid4()}")
    staging.mkdir(parents=True)
    print(f"Recording to {staging}", flush=True)
    start = perf_counter()
    with (staging / "llama-server.log").open("wb") as log:
        process = subprocess.Popen(
            [str(runtime), *arguments], cwd=runtime.parent, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            selector = LocalSelector(port, alias)
            selector.wait_ready(process)
            startup_ms = elapsed(start)
            cohort, filings, controls = write_cases(runner_payload, staging, selector, process.pid, gpu_layers > 0)
        finally:
            process.terminate()
            process.wait(timeout=15)
    report = {
        "strategy": "model_alone", "cohort": cohort, "runner_sha256": sha256(runner_payload).hexdigest(),
        "python": platform.python_version(), "platform": platform.platform(),
        "device_vram_peak_measured": False, "startup_ms": startup_ms, "weights": WEIGHTS, "served_alias": alias,
        "runtime_fingerprint": RUNTIME_FINGERPRINT, "runtime_file_sha256": runtime_files,
        "context_tokens": CONTEXT_SIZE, "threads": 4, "batch_threads": 4, "gpu_layers": gpu_layers,
        "device": device, "parallel": 1,
        "runtime_offline": True, "timeout_seconds": TIMEOUT_SECONDS,
        "sampling": {
            "temperature": 0, "seed": 0, "max_tokens": MAX_RESPONSE_TOKENS,
            "grammar": ROW_ID_GRAMMAR, "grammar_choices": "null and stable row IDs in the current batch",
        },
        "batching": {
            "system_prompt": SYSTEM_PROMPT, "prompt_byte_limit": PROMPT_BYTE_LIMIT,
            "row_fragment_bytes": ROW_FRAGMENT_BYTES, "table_context_bytes": TABLE_CONTEXT_BYTES,
        },
        "code_and_dependency_sha256": code_hashes,
        "filings": filings, "controls": controls,
    }
    (staging / "run.json.gz").write_bytes(gzip.compress(json_bytes(report), mtime=0))
    staging.rename(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runner", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model-dir", type=Path, default=ROOT / ".frag-model")
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--gpu-layers", type=int, default=0)
    parser.add_argument("--device")
    parser.add_argument("--port", type=int, default=18097)
    args = parser.parse_args()
    runtime = args.runtime or args.model_dir / "runtime" / "llama-server.exe"
    run(args.runner, args.output, args.model_dir, runtime, args.port, args.gpu_layers, args.device)


if __name__ == "__main__":
    main()
