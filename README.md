# Research Agent

An agentic research assistant: give it a research goal and it plans, selects
tools, searches, reads sources, scores its own confidence, loops when the
findings are thin, and produces a cited report.

See [RESEARCH_AGENT_SPEC.md](RESEARCH_AGENT_SPEC.md) for the full design.

**Current status: Sprint 1 — scaffold.** Backend serves `/health`; the
frontend calls it and shows the result. No agent yet.

## Run it locally

```bash
cp .env.example .env    # keys can stay blank for Sprint 1
docker compose up --build
```

- Frontend — http://localhost:3000 (green dot means it reached the backend)
- Backend health — http://localhost:8000/health

## Layout

```
backend/    FastAPI app (agent graph lands in Sprint 2)
frontend/   React + Vite, served by nginx, proxies /api to the backend
```

## Notes

- The backend is bind-mounted with `--reload`, so Python edits apply without
  a rebuild. Changing dependencies still needs `docker compose up --build`.
- The frontend container serves a production build. For hot-reload UI work,
  run `npm install && npm run dev` in `frontend/` (port 5173) against the
  containerised backend.
