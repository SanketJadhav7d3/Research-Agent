"""Application settings, loaded from environment variables."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

# Hard safety caps. These are enforced server-side and are never overridable by
# a client request — the deployed demo runs on our own API key, so a caller must
# not be able to ask for unbounded work.
MAX_ITERATIONS_CAP = 3
# Tool calls are budgeted per research round *and* overall. A single cumulative
# cap starves later rounds: the first round spends most of it, leaving the
# gap-filling rounds — the ones that need budget most — with almost none.
MAX_TOOL_CALLS_PER_ROUND = 8
MAX_TOOL_CALLS_TOTAL = 20
MAX_MODEL_TURNS_CAP = 6

# Parallel sub-agents. One worker per sub-question, each with its own context
# window and tool budget. Capped at 3 because the free tiers we run on are
# rate-limited per minute at the organisation level, and every worker's model
# turns come out of the same allowance — more workers would spend the run
# hitting 429s rather than researching.
MAX_PARALLEL_AGENTS = 3
# Per worker, per round. Deliberately smaller than the round budget: several
# workers share MAX_TOOL_CALLS_TOTAL, so one cannot be allowed to drain it.
MAX_TOOL_CALLS_PER_AGENT = 4

# Rate-limit retries. Free tiers meter per minute at the organisation level, so
# parallel sub-agents brush the ceiling in bursts rather than steadily — a few
# patient retries turn a failed run into a slightly slower one. Capped so a
# provider asking for a very long wait fails fast instead of stalling the
# request behind a timeout.
MODEL_RETRY_ATTEMPTS = 4
MODEL_RETRY_MAX_SLEEP = 30.0

# Charting gets its own budget rather than sharing the research one. Code
# often needs a look at the data before it works, and a couple of retries
# must not be able to starve the searches.
MAX_SANDBOX_CALLS = 4
MAX_CHARTS = 3


class Settings(BaseSettings):
    # Paths are resolved from this file, not the working directory, so settings
    # load identically whether run from the repo root, from backend/, or in the
    # container (where only backend/ is present). Later files win.
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    # Comma-separated list of origins allowed to call this API.
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Default provider. Gemini's free tier lets the public demo run without the
    # visitor supplying a key of their own.
    llm_provider: str = "google_genai"
    llm_model: str = "gemini-3.6-flash"

    # Code execution service. Empty disables the feature entirely — forks
    # without the sandbox deployed simply do not get the tool.
    sandbox_url: str = "http://sandbox:8080"

    # Provider keys. Only the default provider's key needs to be set; the others
    # are supplied per-request by users who bring their own.
    google_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Research tool keys.
    tavily_api_key: str = ""
    jina_api_key: str = ""

    @field_validator(
        "google_api_key", "openai_api_key", "anthropic_api_key",
        "tavily_api_key", "jina_api_key",
        mode="after",
    )
    @classmethod
    def _strip_key(cls, value: str) -> str:
        """Trim whitespace from credentials before anything sends them.

        A key stored with a trailing newline — which is what you get from a
        file written on Windows, or an `echo` into a secret — is not a wrong
        key, but it makes an invalid HTTP header, so every request fails with
        a header error rather than an auth error and the cause is easy to
        misread.

        Worse, the client raises with the offending header in the message, so
        an untrimmed key ends up in the logs in plaintext. Stripping here is
        the difference between a working deploy and a leaked credential.
        """
        return value.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
