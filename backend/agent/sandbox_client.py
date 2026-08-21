"""Client for the code execution service.

Kept behind a small interface on purpose: the sandbox is a separate Cloud Run
service today, but nothing above this module knows that. Swapping it for e2b,
or for in-process execution in a test, means replacing this file only.
"""

import logging
import os
import time

import httpx

from config import settings

log = logging.getLogger(__name__)

# Comfortably above the sandbox's own 30s wall clock, so a snippet that is
# killed there reports a real error rather than timing out in transit.
TIMEOUT = 90.0

# The sandbox is deployed private, so calls to it must carry a signed identity
# token. Cloud Run mints one on request from the metadata server, scoped to the
# audience we name — which must be the sandbox's own URL, or it is rejected.
METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/"
    "instance/service-accounts/default/identity"
)
_token: dict = {"value": None, "expires": 0.0}


def _on_cloud_run() -> bool:
    """Cloud Run sets K_SERVICE; nothing else here does.

    Locally the sandbox sits on a private Docker network with no ingress from
    outside, so there is no token to fetch and none needed.
    """
    return bool(os.environ.get("K_SERVICE"))


def _auth_header(audience: str) -> dict[str, str]:
    if not _on_cloud_run():
        return {}

    now = time.time()
    if _token["value"] and _token["expires"] > now + 60:
        return {"Authorization": f"Bearer {_token['value']}"}

    try:
        response = httpx.get(
            METADATA_TOKEN_URL,
            params={"audience": audience},
            headers={"Metadata-Flavor": "Google"},
            timeout=5.0,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.warning("could not mint an identity token: %s", exc)
        return {}

    _token["value"] = response.text.strip()
    # Tokens last an hour. Refreshed well before that rather than parsing the
    # JWT, which would mean carrying a decoder for one field.
    _token["expires"] = now + 45 * 60
    return {"Authorization": f"Bearer {_token['value']}"}


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
    base = settings.sandbox_url.rstrip("/")
    try:
        response = httpx.post(
            f"{base}/execute",
            json={"code": code, "data": data if data is not None else []},
            headers=_auth_header(base),
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        # 403 here almost always means the backend's service account is missing
        # run.invoker on the sandbox, so say that rather than leaving a bare
        # status code in the trace.
        if exc.response.status_code in (401, 403):
            log.error("sandbox rejected the call: %s", exc.response.status_code)
            return _unreachable(
                "The sandbox refused the request. The backend's service account "
                "likely lacks roles/run.invoker on it."
            )
        log.warning("sandbox returned %s", exc.response.status_code)
        return _unreachable(f"The sandbox returned HTTP {exc.response.status_code}.")
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
