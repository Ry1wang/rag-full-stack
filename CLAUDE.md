# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Full-stack web application template: FastAPI backend + React/TypeScript frontend, PostgreSQL database, Docker Compose orchestration.

## Commands

### Full Stack (Docker)
```bash
docker compose watch          # Start full stack with hot reload
bash ./scripts/test.sh        # Run all tests in Docker
```

### Backend (run from `backend/`)
```bash
uv sync                       # Install dependencies
fastapi dev app/main.py       # Dev server (auto-reload, port 8000)
uv run pytest                 # Run all tests
uv run pytest tests/api/routes/items.py  # Run a single test file
uv run ruff check             # Lint
uv run ruff format            # Format
uv run mypy app               # Type check (strict mode)
```

### Frontend (run from `frontend/`)
```bash
bun install                   # Install dependencies
bun run dev                   # Vite dev server (port 5173)
bun run build                 # Production build
bun run lint                  # Biome lint/format
bun run generate-client       # Regenerate OpenAPI client from backend schema
bunx playwright test          # E2E tests
bunx playwright test --ui     # E2E tests in interactive mode
```

## Architecture

### Backend (`backend/app/`)
- `main.py` — FastAPI app setup, CORS, Sentry
- `core/` — Config (settings from env), DB session, security utilities
- `api/routes/` — Route handlers: `login.py`, `users.py`, `items.py`, `utils.py`
- `models.py` — SQLModel models (User, Item) — single source of truth for DB schema + Pydantic validation
- `crud.py` — Database operations
- `alembic/` — DB migrations

### Frontend (`frontend/src/`)
- `routes/` — File-based routing via TanStack Router; `_layout.tsx` is the authenticated shell
- `client/` — **Auto-generated** OpenAPI client (never edit manually; regenerate with `bun run generate-client`)
- `components/` — shadcn/ui-based components
- `hooks/` — Custom React hooks

### Key Patterns
- **API Client**: Generated from FastAPI's OpenAPI schema. After changing backend models/routes, run `bun run generate-client` in `frontend/`.
- **Auth**: JWT stored in localStorage; 401/403 responses redirect to login. Backend validates via FastAPI dependency injection.
- **Database**: SQLModel (SQLAlchemy + Pydantic). Add new models to `models.py`, then create an Alembic migration (`alembic revision --autogenerate`).
- **Config**: All settings loaded from environment via `app/core/config.py`. `.env` at project root.

### Dev URLs
| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| Adminer (DB UI) | http://localhost:8080 |
| Mailcatcher | http://localhost:1080 |

## Environment Setup

Copy `.env.example` to `.env`. Required values: `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD`, `POSTGRES_PASSWORD`.

Generate a secret key: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

## Pre-commit Hooks

The project uses `prek` (configured in `.pre-commit-config.yaml`) for: Ruff lint/format, MyPy, Biome, and automatic client regeneration when backend files change.
