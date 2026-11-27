"""Compare complete Phase 6 replay payloads."""

import json
from typing import Any


PAYLOADS = ("result", "citations")


def differing_payloads(live: dict[str, Any], replay: dict[str, Any]) -> list[str]:
    return [
        field for field in PAYLOADS
        if not isinstance(live.get(field), dict) or not isinstance(replay.get(field), dict)
        or json.dumps(live[field], sort_keys=True) != json.dumps(replay[field], sort_keys=True)
    ]
