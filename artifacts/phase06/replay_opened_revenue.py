"""Replay the issue #39 results and citation responses from preserved originals."""

import argparse
import gzip
import json
from pathlib import Path
import socket
import sys


PHASE = Path(__file__).resolve().parent
ROOT = PHASE.parents[1]
sys.path.insert(0, str(PHASE.parent / "phase04"))
from sec_holdout_runner import ingest, replay_case


def deny_network(*args, **kwargs):
    raise AssertionError("Network access attempted during replay")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    work = parser.parse_args().work
    work.mkdir(parents=True)
    socket.socket = socket.create_connection = socket.getaddrinfo = deny_network

    reviews = json.loads((ROOT / "tests/fixtures/phase06_ge_hd_ups_review.json").read_bytes())
    saved = json.loads(gzip.decompress((PHASE / "ge-hd-ups-validation.json.gz").read_bytes()))
    store = work / "store"
    for filename, review in reviews.items():
        original = work / filename
        original.write_bytes(gzip.decompress((PHASE / "originals" / (filename + ".gz")).read_bytes()))
        source = ingest(store, original, review["source"])
        original.unlink()
        if source.get("source_hash") != review["source"]["sha256"]:
            raise ValueError(f"{filename} does not match the original custody hash.")
        for case in review["cases"]:
            case_id = case["case_id"]
            outcome = replay_case(store, case, source, saved["cases"][case_id])
            if outcome != {"status": "matched"}:
                raise ValueError(f"{case_id} replay failed: {outcome['status']}")
            print(case_id, "matched")


if __name__ == "__main__":
    main()
