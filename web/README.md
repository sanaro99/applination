# Applination — web frontend

Next.js 16 (App Router) frontend for [Applination](https://github.com/sanaro99/applination).

For full documentation — features, getting started, configuration, and architecture — see the [root README](../README.md).

## Dev commands

```bash
npm run dev      # development server on :3000 (Turbopack)
npm run build    # production build
npm run start    # serve production build on :3000
npm run lint     # ESLint
```

Run alongside the FastAPI backend (`python -m uvicorn server.app:app --reload --port 8000`), or use `.\scripts\dev.ps1` from the project root to start both at once.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `http://127.0.0.1:8000` | Override API URL (e.g. for remote deploy) |
