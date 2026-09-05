"""Provider-agnostic model construction.

Every node gets its model from here, so switching provider is a config change
rather than a code change. `init_chat_model` accepts a "provider:model" string
and returns a uniform interface, including `.with_structured_output()`.
"""

import logging
import random
import re
import time

from langchain.chat_models import init_chat_model

from config import MODEL_RETRY_ATTEMPTS, MODEL_RETRY_MAX_SLEEP
from config import settings

log = logging.getLogger(__name__)

# Providers the app knows how to build, mapped to the env var holding their key.
SUPPORTED_PROVIDERS = {
    "google_genai": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

# Used when the caller names a provider but not a model.
DEFAULT_MODELS = {
    "google_genai": "gemini-3.6-flash",
    "openai": "gpt-5.5",
    "anthropic": "claude-opus-5",
}


def _resolve_key(provider: str, api_key: str | None) -> str:
    """A caller-supplied key wins; otherwise fall back to the server's own."""
    if api_key:
        return api_key
    return {
        "google_genai": settings.google_api_key,
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
    }[provider]


def get_model(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
):
    """Build a chat model.

    api_key is passed explicitly rather than read from the environment so that a
    user's own key can be used for one request without ever being stored.
    """
    provider = provider or settings.llm_provider
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported provider {provider!r}. "
            f"Expected one of: {', '.join(SUPPORTED_PROVIDERS)}"
        )

    model = model or (
        settings.llm_model
        if provider == settings.llm_provider
        else DEFAULT_MODELS[provider]
    )

    key = _resolve_key(provider, api_key)
    if not key:
        raise ValueError(
            f"No API key for {provider}. Set {SUPPORTED_PROVIDERS[provider]} "
            f"in your .env, or supply a key with the request."
        )

    return init_chat_model(f"{provider}:{model}", api_key=key)


# Substrings that identify a "slow down" rather than a real failure. Providers
# disagree on the wording and on the exception class, and the free tiers this
# runs on are exactly where the difference matters, so match on the text rather
# than importing three provider-specific error types.
_RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "resource_exhausted",
    "resourceexhausted",
    "quota",
    "too many requests",
    "overloaded",
    "503",
    "529",
)

# "retry_delay { seconds: 27 }" (Gemini) or "retry-after: 27" (header echoed
# into the message by some clients).
_DELAY_PATTERN = re.compile(
    r"(?:retry[-_ ]?(?:delay|after)\D{0,20}?)(\d+(?:\.\d+)?)", re.IGNORECASE
)


def is_rate_limit(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _RATE_LIMIT_MARKERS)


def _server_delay(exc: BaseException) -> float | None:
    """The wait the provider asked for, if it named one.

    Honouring this beats guessing: a provider that says 27 seconds means it,
    and backing off for 4 just burns another request against the same quota.
    """
    for attr in ("retry_after", "retry_delay"):
        value = getattr(exc, attr, None)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        seconds = getattr(value, "seconds", None)  # google's protobuf Duration
        if isinstance(seconds, (int, float)) and seconds > 0:
            return float(seconds)

    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers:
        try:
            raw = headers.get("retry-after") or headers.get("Retry-After")
            if raw:
                return float(raw)
        except (TypeError, ValueError):
            pass

    match = _DELAY_PATTERN.search(str(exc))
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def invoke_with_retry(runnable, payload, *, label: str = "model"):
    """Invoke a runnable, backing off and retrying when rate-limited.

    Applied at the call site rather than inside get_model() because the useful
    object is whatever the node has already built — `.bind_tools(...)` or
    `.with_structured_output(...)` — and LangChain's own `.with_retry()`
    returns a runnable that no longer offers either.

    Only rate limits and transient overload are retried. A bad key or a
    malformed request will fail identically on the second attempt, so raising
    immediately gets the real error in front of the caller instead of burying
    it under a minute of sleeping.
    """
    for attempt in range(1, MODEL_RETRY_ATTEMPTS + 1):
        try:
            return runnable.invoke(payload)
        except Exception as exc:  # noqa: BLE001 - re-raised unless retryable
            if not is_rate_limit(exc) or attempt == MODEL_RETRY_ATTEMPTS:
                raise
            # Exponential backoff, with jitter so that sub-agents throttled by
            # the same limit at the same moment do not all wake together and
            # trip it again.
            delay = _server_delay(exc) or min(2 ** attempt, MODEL_RETRY_MAX_SLEEP)
            delay = min(delay, MODEL_RETRY_MAX_SLEEP) + random.uniform(0, 1)
            log.warning(
                "%s rate-limited (attempt %d/%d), retrying in %.1fs: %s",
                label, attempt, MODEL_RETRY_ATTEMPTS, delay, exc,
            )
            time.sleep(delay)
