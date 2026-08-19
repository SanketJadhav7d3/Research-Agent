"""FastAPI application entrypoint.

Sprint 1 scope: a health endpoint only. The agent graph and the /research
SSE stream arrive in later sprints.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings

app = FastAPI(title="Research Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Used by Docker Compose and Cloud Run health checks."""
    return {"status": "ok"}
