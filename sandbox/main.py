"""HTTP front door for the sandbox.

Deliberately dumb: it takes {code, data} and returns what running the code
produced. No findings store, no fetching, no agent logic. One trust boundary,
and it is easy to describe — which is the point.

In production this service is private, callable only by the backend's service
account, and runs with an IAM-less service account of its own.
"""

import logging

from fastapi import FastAPI
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import runner

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Research Agent Sandbox", version="0.1.0")

MAX_CODE_CHARS = 20_000


class ExecuteRequest(BaseModel):
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    # Findings for this run. Shape is whatever the agent gathered — the
    # executed code is responsible for working it out.
    data: list | dict | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/execute")
async def execute(req: ExecuteRequest) -> dict:
    """Run one snippet.

    Always 200. A failure is a result the agent needs to read and act on, not
    an HTTP error — returning 500 for a syntax error would make the caller's
    retry logic fight the transport layer.
    """
    log.info("execute: %d chars of code", len(req.code))
    # Blocking subprocess work, kept off the event loop so the health check
    # still answers while a snippet is running.
    return await run_in_threadpool(runner.execute, req.code, req.data)
