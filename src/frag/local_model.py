"""One planning request to the pinned llama.cpp server on IPv4 loopback."""

import http.client
import json
from typing import Any

HOST = "127.0.0.1"
PORT = 8087
TIMEOUT_SECONDS = 30
MODEL_ALIAS = "frag-qwen25-05b-q4km"
RUNTIME_FINGERPRINT = "b6500-a7a98e0f"
MODEL_SETTINGS = {
    "runtime": f"llama.cpp {RUNTIME_FINGERPRINT}",
    "weights": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
    "revision": "9217f5db79a29953eb74d5343926648285ec7e67",
    "quantization": "Q4_K_M",
    "context_size": 4096,
    "threads": 4,
    "gpu_layers": 0,
    "parallel": 1,
    "offline": True,
    "timeout_seconds": TIMEOUT_SECONDS,
}


class ModelUnavailable(Exception):
    pass


class InvalidModelResponse(Exception):
    pass


def propose_lookup(
    payload: dict[str, Any], *, expected_model: str | None = None, port: int | None = None,
) -> str:
    connection = http.client.HTTPConnection(HOST, PORT if port is None else port, timeout=TIMEOUT_SECONDS)
    try:
        connection.request(
            "POST", "/v1/chat/completions", json.dumps(payload),
            {"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ModelUnavailable
        body = response.read(64 * 1024 + 1)
    except TimeoutError:
        raise
    except (OSError, http.client.HTTPException) as error:
        raise ModelUnavailable from error
    finally:
        connection.close()

    try:
        if len(body) > 64 * 1024:
            raise ValueError
        decoded = json.loads(body)
        if (decoded["model"] != (expected_model or MODEL_ALIAS)
                or decoded["system_fingerprint"] != RUNTIME_FINGERPRINT):
            raise ModelUnavailable
        choice = decoded["choices"][0]
        proposal = choice["message"]["content"]
        if not isinstance(proposal, str):
            raise ValueError
        return proposal
    except (KeyError, IndexError, TypeError, ValueError, RecursionError) as error:
        raise InvalidModelResponse from error
