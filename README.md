# Research Agent

An agentic research assistant: give it a research goal and it plans, selects
tools, searches, reads sources, scores its own confidence, loops when the
findings are thin, and produces a cited report.

## Run it locally

```bash
cp .env.example .env    # add GOOGLE_API_KEY and TAVILY_API_KEY
docker compose up --build
```

- Frontend — http://localhost:3000
- Backend health — http://localhost:8000/health

## Layout

```
backend/    FastAPI app and the LangGraph agent
frontend/   React + Vite, served by nginx, proxies /api to the backend
```

## Notes

- The backend is bind-mounted with `--reload`, so Python edits apply without
  a rebuild. Changing dependencies still needs `docker compose up --build`.
- The frontend container serves a production build. For hot-reload UI work,
  run `npm install && npm run dev` in `frontend/` (port 5173) against the
  containerised backend.
