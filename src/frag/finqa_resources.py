"""Measure a fresh local FinQA server and a warm cohort on Windows."""

import http.client
import json
import os
import platform
import socket
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from hashlib import file_digest
from pathlib import Path
from statistics import median
from threading import Event, Thread
from time import perf_counter, sleep
from typing import Any

from frag import local_model

MODEL = {
    "alias": "frag-qwen25-15b-q4km",
    "repository": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
    "revision": "91cad51170dc346986eccefdc2dd33a9da36ead9",
    "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "sha256": "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
    "quantization": "Q4_K_M",
}
RUNTIME_ARGS = ("--offline", "--ctx-size", "4096", "--threads", "4", "--n-gpu-layers", "0", "--parallel", "1")
RUNTIME_SHA256 = "62e6a5fec588ff3ea6d26a507db4373e56c850db19b39239bd30f5e7d87751cd"
GPU_INTERVAL_SECONDS = 0.1


def _check_digest(path: Path, expected: str) -> None:
    with path.open("rb") as source:
        if file_digest(source, "sha256").hexdigest() != expected:
            raise ValueError(f"SHA-256 mismatch for {path}")


def _wait_until_ready(process: subprocess.Popen[bytes], port: int) -> None:
    deadline = perf_counter() + 30
    while perf_counter() < deadline and process.poll() is None:
        connection = http.client.HTTPConnection(local_model.HOST, port, timeout=1)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            if response.status == 200 and json.loads(response.read()).get("status") == "ok":
                return
        except OSError:
            pass
        finally:
            connection.close()
        sleep(0.05)
    raise RuntimeError(f"FinQA local server did not become ready (exit status {process.poll()})")


def _ram_peak(pid: int) -> int:
    result = subprocess.check_output(
        ["powershell.exe", "-NoProfile", "-Command", f"(Get-Process -Id {pid}).PeakWorkingSet64"],
        text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return int(result.strip())


def _gpu_snapshot() -> dict[str, int] | None:
    try:
        result = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,name,memory.used", "--format=csv,noheader,nounits"],
            text=True, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, timeout=2,
        )
        devices = {}
        for line in result.splitlines():
            index, name, mib = line.split(", ")
            devices[f"{index} {name}"] = int(mib)
        return devices or None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


@contextmanager
def _sample_vram() -> Iterator[dict[str, Any]]:
    baseline = _gpu_snapshot()
    stats: dict[str, Any] = {
        "baseline_mib_by_device": baseline, "sampled_peak_mib_by_device": None,
        "samples": 0, "interval_seconds": GPU_INTERVAL_SECONDS,
    }
    stop = Event()

    def sample() -> None:
        while not stop.is_set():
            snapshot = _gpu_snapshot()
            if snapshot is not None:
                stats["samples"] += 1
                peak = stats["sampled_peak_mib_by_device"] or {}
                stats["sampled_peak_mib_by_device"] = {
                    name: max(peak.get(name, 0), mib) for name, mib in snapshot.items()
                }
            stop.wait(GPU_INTERVAL_SECONDS)

    thread = Thread(target=sample)
    thread.start()
    try:
        yield stats
    finally:
        stop.set()
        thread.join()


def measure(
    model_directory: Path, rows: list[dict[str, Any]], evaluate: Callable[[dict[str, Any], int], dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if os.name != "nt":
        raise ValueError("FinQA resource measurement requires Windows")
    runtime = model_directory / "runtime" / "llama-server.exe"
    weights = model_directory / MODEL["filename"]
    _check_digest(runtime, RUNTIME_SHA256)
    _check_digest(weights, MODEL["sha256"])
    with socket.socket() as listener:
        listener.bind((local_model.HOST, 0))
        port = int(listener.getsockname()[1])
    settings = [
        str(runtime.resolve()), "--log-disable", "--model", str(weights.resolve()), "--alias", MODEL["alias"],
        "--host", local_model.HOST, "--port", str(port), *RUNTIME_ARGS,
    ]
    process = None
    try:
        with _sample_vram() as cold_vram:
            started = perf_counter()
            process = subprocess.Popen(settings, creationflags=subprocess.CREATE_NO_WINDOW)
            _wait_until_ready(process, port)
            ready = perf_counter()
            cold = evaluate(rows[0], port)
            cold_finished = perf_counter()
            cold_ram_peak = _ram_peak(process.pid)
        with _sample_vram() as warm_vram:
            warm_started = perf_counter()
            warm = [evaluate(row, port) for row in rows]
            warm_elapsed = perf_counter() - warm_started
            run_ram_peak = _ram_peak(process.pid)
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=10)
    return warm, {
        "platform": platform.platform(), "processor": os.environ.get("PROCESSOR_IDENTIFIER"),
        "server_ready_seconds": round(ready - started, 3),
        "cold_start_and_question_seconds": round(cold_finished - started, 3), "cold_case": cold,
        "warm_cohort_seconds": round(warm_elapsed, 3),
        "warm_median_question_seconds": median(case["elapsed_seconds"] for case in warm),
        "cold_peak_server_working_set_bytes": cold_ram_peak,
        "run_peak_server_working_set_bytes": run_ram_peak,
        "cold_vram": cold_vram, "warm_vram": warm_vram,
    }
