"""Client for the code execution service.

Kept behind a small interface on purpose: the sandbox is a separate Cloud Run
service today, but nothing above this module knows that. Swapping it for e2b,
or for in-process execution in a test, means replacing this file only.
"""

import logging

import httpx

from config import settings

log = logging.getLogger(__name__)

# Comfortably above the sandbox's own 30s wall clock, so a snippet that is
# killed there reports a real error rather than timing out in transit.
TIMEOUT = 90.0


def available() -> bool:
    """Whether code execution is configured at all.

    Local forks and anyone without the sandbox deployed simply do not get the
    tool. Binding a tool that always fails is worse than not binding it: it
    wastes budget every round and muddles the model's planning.
    """
    return bool(settings.sandbox_url)


def execute(code: str, data: list | dict | None = None) -> dict:
    """Run code in the sandbox.

    Never raises. A failure to reach the service is returned in the same shape
    as a failure inside it, so callers have one path to handle.
    """
    try:
        response = httpx.post(
            f"{settings.sandbox_url.rstrip('/')}/execute",
            json={"code": code, "data": data if data is not None else []},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except httpx.TimeoutException:
        log.warning("sandbox timed out after %.0fs", TIMEOUT)
        return _unreachable(f"The sandbox did not respond within {TIMEOUT:.0f}s.")
    except Exception as exc:  # noqa: BLE001 - surfaced to the model
        log.warning("sandbox call failed: %s", exc)
        return _unreachable(f"The sandbox could not be reached: {exc}")


def _unreachable(message: str) -> dict:
    return {
        "stdout": "",
        "stderr": message,
        "error": "SandboxUnavailable",
        "charts": [],
        "truncated": False,
    }
