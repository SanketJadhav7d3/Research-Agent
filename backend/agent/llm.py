"""Provider-agnostic model construction.

Every node gets its model from here, so switching provider is a config change
rather than a code change. `init_chat_model` accepts a "provider:model" string
and returns a uniform interface, including `.with_structured_output()`.
"""

from langchain.chat_models import init_chat_model

from config import settings

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
