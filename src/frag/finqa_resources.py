"""Measure a fresh local FinQA server and a warm cohort on Windows."""

import http.client
import ctypes
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
from zipfile import ZipFile

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
RUNTIME_ARCHIVE_SHA256 = "73e00267e852e666a6fce2c3fb7a2603dd1934a37259f3f45c2c1b6983fa605a"
SAMPLE_INTERVAL_SECONDS = 0.1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_ulong), ("page_fault_count", ctypes.c_ulong),
        ("peak_working_set_size", ctypes.c_size_t), ("working_set_size", ctypes.c_size_t),
        ("quota_peak_paged_pool_usage", ctypes.c_size_t), ("quota_paged_pool_usage", ctypes.c_size_t),
        ("quota_peak_nonpaged_pool_usage", ctypes.c_size_t), ("quota_nonpaged_pool_usage", ctypes.c_size_t),
        ("pagefile_usage", ctypes.c_size_t), ("peak_pagefile_usage", ctypes.c_size_t),
    ]


def _check_digest(path: Path, expected: str) -> None:
    with path.open("rb") as source:
        if file_digest(source, "sha256").hexdigest() != expected:
            raise ValueError(f"SHA-256 mismatch for {path}")


def _verify_runtime(model_directory: Path, executable: Path) -> None:
    archive_path = model_directory / "runtime.zip"
    _check_digest(archive_path, RUNTIME_ARCHIVE_SHA256)
    _check_digest(executable, RUNTIME_SHA256)
    with ZipFile(archive_path) as archive:
        libraries = {name for name in archive.namelist() if name.endswith(".dll")}
        if {path.name for path in executable.parent.glob("*.dll")} != libraries:
            raise ValueError("Runtime DLL set differs from the pinned archive")
        for name in sorted(libraries):
            if executable.with_name(name).read_bytes() != archive.read(name):
                raise ValueError(f"Runtime DLL differs from the pinned archive: {name}")


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


@contextmanager
def _process_working_set(pid: int) -> Iterator[Callable[[], tuple[int, int] | None]]:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel.CloseHandle.restype = ctypes.c_int
    psapi.GetProcessMemoryInfo.argtypes = (ctypes.c_void_p, ctypes.POINTER(ProcessMemoryCounters), ctypes.c_ulong)
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    memory = ProcessMemoryCounters()
    memory.size = ctypes.sizeof(memory)

    def read() -> tuple[int, int] | None:
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.size):
            return int(memory.working_set_size), int(memory.peak_working_set_size)
        return None

    try:
        yield read
    finally:
        kernel.CloseHandle(handle)


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
def _sample_periodically(sample: Callable[[], None]) -> Iterator[None]:
    stop = Event()

    def collect() -> None:
        while not stop.is_set():
            sample()
            stop.wait(SAMPLE_INTERVAL_SECONDS)

    thread = Thread(target=collect)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


@contextmanager
def _sample_vram() -> Iterator[dict[str, Any]]:
    stats: dict[str, Any] = {
        "baseline_mib_by_device": _gpu_snapshot(), "sampled_peak_mib_by_device": None,
        "samples": 0, "interval_seconds": SAMPLE_INTERVAL_SECONDS,
    }

    def sample() -> None:
        snapshot = _gpu_snapshot()
        if snapshot is not None:
            stats["samples"] += 1
            peak = stats["sampled_peak_mib_by_device"] or {}
            stats["sampled_peak_mib_by_device"] = {
                name: max(peak.get(name, 0), mib) for name, mib in snapshot.items()
            }

    with _sample_periodically(sample):
        yield stats


def measure(
    model_directory: Path, rows: list[dict[str, Any]], evaluate: Callable[[dict[str, Any], int], dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if os.name != "nt":
        raise ValueError("FinQA resource measurement requires Windows")
    runtime = model_directory / "runtime" / "llama-server.exe"
    weights = model_directory / MODEL["filename"]
    _verify_runtime(model_directory, runtime)
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
            with _process_working_set(process.pid) as read:
                cold_ram = read()
        warm_ram_samples = []
        with _process_working_set(process.pid) as read, _sample_vram() as warm_vram:
            def sample_working_set() -> None:
                current = read()
                if current is not None:
                    warm_ram_samples.append(current[0])

            with _sample_periodically(sample_working_set):
                warm_started = perf_counter()
                warm = [evaluate(row, port) for row in rows]
                warm_elapsed = perf_counter() - warm_started
            run_ram = read()
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
        "cold_peak_server_working_set_bytes": cold_ram[1] if cold_ram else None,
        "warm_sampled_peak_server_working_set_bytes": max(warm_ram_samples, default=None),
        "warm_working_set_samples": len(warm_ram_samples),
        "warm_working_set_interval_seconds": SAMPLE_INTERVAL_SECONDS,
        "run_peak_server_working_set_bytes": run_ram[1] if run_ram else None,
        "cold_vram": cold_vram, "warm_vram": warm_vram,
    }
