"""Run and replay the Phase 5 development questions against a frozen checkout."""

import argparse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from ctypes import Structure, WinDLL, byref, c_size_t, sizeof, wintypes
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import platform
import socket
import subprocess
import sys
from threading import Event
from time import perf_counter, sleep
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase04"))

from sec_holdout_runner import (
    ROOT, WEIGHTS_SHA256, ask_case, digest, freeze_inputs, ingest,
    read_json, replay_case, restrict_runner, runtime_hashes, write_json,
)
from frag import local_model
from frag.lookup import GENERATION_SETTINGS

PHASE = Path("artifacts/phase05")
MIB = 1024 ** 2
GPU_QUERY = "index,name,memory.total,memory.used"


class MemoryCounters(Structure):
    _fields_ = [
        ("size", wintypes.DWORD), ("page_faults", wintypes.DWORD),
        *((name, c_size_t) for name in (
            "peak_working_set", "working_set", "peak_paged_pool", "paged_pool",
            "peak_nonpaged_pool", "nonpaged_pool", "pagefile", "peak_pagefile",
        )),
    ]


def working_set_mib(process: subprocess.Popen[bytes]) -> dict[str, float]:
    kernel = WinDLL("kernel32")
    api = WinDLL("psapi").GetProcessMemoryInfo
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    api.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD]
    peaks = {}
    for name, handle in (("runner", kernel.GetCurrentProcess()), ("planner", int(process._handle))):  # type: ignore[attr-defined]
        counters = MemoryCounters()
        counters.size = sizeof(counters)
        if not api(handle, byref(counters), counters.size):
            raise OSError(f"Could not measure {name} working set")
        peaks[name] = round(counters.peak_working_set / MIB, 2)
    return peaks


def sample_gpu(stop: Event) -> list[int]:
    observations = []
    while not stop.is_set():
        output = subprocess.check_output(
            ["nvidia-smi", f"--query-gpu={GPU_QUERY}", "--format=csv,noheader,nounits"],
            text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        observations.append(sum(int(row.rsplit(",", 1)[-1]) for row in output.splitlines()))
        stop.wait(0.05)
    return observations


def settings(data: Path | None) -> dict[str, Any]:
    config = freeze_inputs()
    config["files"].update({
        path.relative_to(ROOT).as_posix(): digest(path)
        for path in sorted([
            *(ROOT / "src/frag").glob("*.json"),
            ROOT / "scripts/setup-local-model.ps1",
            ROOT / PHASE / "baseline.py", ROOT / PHASE / "score.py",
        ])
    })
    return {
        **config, **({"inputs_sha256": digest(data / PHASE / "inputs.json")} if data is not None else {}),
        "retrieval": {
            "entry_point": "filing-scoped frag ask",
            "index": "selected filing's verified annual revenue facts",
            "lookup": "dated parser filters eligible facts to requested FY; Microsoft retains eligible facts",
            "growth": "dated parser selects the requested pair; Microsoft retains eligible facts",
            "context_fields": ["fact_id", "metric", "reporting_period", "normalized_amount", "currency", "scale"],
            "generation": GENERATION_SETTINGS,
            "max_tokens": {"lookup": 120, "growth": 320},
        },
    }


def server_command(model: Path, port: int) -> list[str]:
    settings = local_model.MODEL_SETTINGS
    return [
        str(model / "runtime/llama-server.exe"), "--offline", "--model", str(model / "model.gguf"),
        "--alias", local_model.MODEL_ALIAS, "--host", local_model.HOST, "--port", str(port),
        "--ctx-size", str(settings["context_size"]), "--threads", str(settings["threads"]),
        "--n-gpu-layers", str(settings["gpu_layers"]), "--parallel", str(settings["parallel"]), "--log-disable",
    ]


def start_server(model: Path, port: int) -> subprocess.Popen[bytes]:
    with socket.socket() as probe:
        probe.bind((local_model.HOST, port))
    return subprocess.Popen(server_command(model, port), stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


def health(planner: subprocess.Popen[bytes]) -> None:
    deadline = perf_counter() + 30
    while perf_counter() < deadline:
        if planner.poll() is not None:
            raise RuntimeError(f"The planner exited with status {planner.returncode}.")
        try:
            with urlopen(f"http://{local_model.HOST}:{local_model.PORT}/health", timeout=1) as response:
                if json.load(response).get("status") == "ok":
                    return
        except (URLError, TimeoutError):
            sleep(0.1)
    raise RuntimeError("The frozen local planner did not become healthy.")


def measure(
    model: Path, store: Path, case: dict[str, Any], source: dict[str, Any], work: Path,
) -> dict[str, Any]:
    stop = Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        started = perf_counter()
        planner = start_server(model, local_model.PORT)
        sampler = pool.submit(sample_gpu, stop)
        try:
            health(planner)
            startup_ms = round((perf_counter() - started) * 1000, 3)
            case_id = case["case_id"]
            cold = ask_case(store, case, source, work / f"{case_id}-cold.json")
            warm = ask_case(store, case, source, work / f"{case_id}-warm.json")
            peaks = working_set_mib(planner)
        finally:
            stop.set()
            planner.terminate()
            planner.wait(timeout=10)
        samples = sampler.result()
    if not samples:
        raise RuntimeError("No GPU use samples were recorded.")
    return {
        "cold": cold, "warm": warm, "planner_startup_ms": startup_ms,
        "peak_working_set_mib": peaks, "peak_device_vram_mib": max(samples),
        "vram_sample_count": len(samples),
    }


def ingest_evidence(store: Path, original: Path, filing: dict[str, Any]) -> dict[str, Any]:
    evidence = ingest(store, original, filing)
    evidence.pop("original_path", None)
    if "provenance" in evidence:
        evidence["provenance"].pop("input_path", None)
        evidence["provenance"].pop("preserved_at", None)
    return evidence


def evaluate(
    data: Path, work: Path, frozen: dict[str, Any], model: Path | None,
    previous: dict[str, Any] | None,
    *, replay_question: Callable[[Path, dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]] = replay_case,
    require_equal_intake: bool = True,
) -> dict[str, Any]:
    manifest = read_json(data / PHASE / "inputs.json")
    work.mkdir()
    store = work / "store"
    sources: dict[str, Any] = {}
    for filing in manifest["sources"]:
        archive = data / filing["archive"]
        original_bytes = gzip.decompress(archive.read_bytes())
        original = work / filing["original_filename"]
        original.write_bytes(original_bytes)
        if (digest(archive) != filing["archive_sha256"] or digest(original) != filing["sha256"]
                or len(original_bytes) != filing["byte_length"]):
            raise ValueError(f"Source identity mismatch for {original.name}.")
        start = perf_counter()
        evidence = ingest_evidence(store, original, filing)
        if "command_error" not in evidence and evidence["source_hash"] != filing["sha256"]:
            raise ValueError(f"Ingestion identity mismatch for {original.name}.")
        sources[filing["source_id"]] = {
            "evidence": evidence, "ingest_ms": round((perf_counter() - start) * 1000, 3),
        }
    cases = manifest["cases"]
    intake_differences = []
    if previous is not None:
        if previous["freeze"] != frozen or [row["case"] for row in previous["cases"]] != cases:
            raise ValueError("Replay inputs differ from the live run.")
        live_sources = previous["sources"]
        intake_differences = sorted(
            key for key in live_sources.keys() | sources.keys()
            if live_sources.get(key, {}).get("evidence") != sources.get(key, {}).get("evidence")
        )
        if require_equal_intake and intake_differences:
            raise ValueError("Reingested evidence differs from the live run.")
    results = []
    for index, case in enumerate(cases):
        source = sources[case["source_id"]]["evidence"]
        if model is not None:
            row = measure(model, store, case, source, work)
        else:
            assert previous is not None
            saved = previous["cases"][index]
            row = {
                mode: replay_question(
                    store, {**case, "case_id": f'{case["case_id"]}-{mode}'}, source, saved[mode],
                )
                for mode in ("cold", "warm")
            }
        results.append({"case": case, **row})
    report = {"freeze": frozen, "sources": sources, "cases": results}
    if not require_equal_intake and previous is not None:
        report["differing_intake_sources"] = intake_differences
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "live", "replay"))
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--freeze", required=True, type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--port", type=int, default=18089)
    parser.add_argument("--commit")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--live", type=Path)
    args = parser.parse_args()
    config = settings(args.data)
    if args.mode in ("freeze", "live"):
        if args.model is None or digest(args.model / "model.gguf") != WEIGHTS_SHA256:
            parser.error("Specify the directory containing the pinned model and runtime.")
        config["runtime_files"] = runtime_hashes(args.model)
    if args.mode == "freeze":
        if not args.commit or args.reference is None or not 1 <= args.port <= 65535:
            parser.error("Specify the production commit, scoring reference and a dedicated loopback port.")
        gpu = subprocess.check_output(
            ["nvidia-smi", f"--query-gpu={GPU_QUERY}", "--format=csv,noheader,nounits"], text=True, timeout=5,
        ).strip()
        write_json(args.freeze, {
            **config, "production_commit": args.commit, "port": args.port, "gpu_at_freeze": gpu,
            "reference_sha256": digest(args.reference),
            "created_at_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
            "cpu": platform.processor(),
        })
        return
    if args.work is None or (args.mode == "replay") != bool(args.live):
        parser.error("Provide a fresh work directory and, for replay, the saved live report.")
    frozen = read_json(args.freeze)
    if any(frozen.get(key) != value for key, value in config.items()):
        parser.error("Frozen code, model, dependencies or inputs differ.")
    local_model.PORT = frozen["port"]
    previous = None
    if args.mode == "replay":
        previous = read_json(args.live)
        # The snapshot guard blocks every connection during offline replay.
        restrict_runner(replay=True)
    report = evaluate(args.data, args.work, frozen, args.model if args.mode == "live" else None, previous)
    write_json(args.work / "report.json", report)
    if args.mode == "replay":
        matches = sum(row[mode]["status"] == "matched" for row in report["cases"] for mode in ("cold", "warm"))
        print(f"{matches}/{2 * len(report['cases'])} cold and warm results and citations matched")
        if matches != 2 * len(report["cases"]):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
