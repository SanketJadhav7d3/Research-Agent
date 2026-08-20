"""Application settings, loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict

# Hard safety caps. These are enforced server-side and are never overridable by
# a client request — the deployed demo runs on our own API key, so a caller must
# not be able to ask for unbounded work.
MAX_ITERATIONS_CAP = 3
MAX_TOOL_CALLS_CAP = 12
MAX_MODEL_TURNS_CAP = 6


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Comma-separated list of origins allowed to call this API.
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Default provider. Gemini's free tier lets the public demo run without the
    # visitor supplying a key of their own.
    llm_provider: str = "google_genai"
    llm_model: str = "gemini-2.5-flash"

    # Provider keys. Only the default provider's key needs to be set; the others
    # are supplied per-request by users who bring their own.
    google_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
