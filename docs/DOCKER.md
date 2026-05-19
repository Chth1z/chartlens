# Docker Setup

One-command local development and production deployment for EYEX.

## Quick Start

```bash
# Create var directory for persistent storage (if it doesn't exist)
mkdir -p var/storage

# Copy environment file
cp .env.example .env

# Build and run
docker compose up --build
```

The app is available at `http://localhost:8000`.

## Architecture

The Docker setup uses a multi-stage build:

1. **Stage 1 (frontend-build)**: Node 24 Alpine builds the Vite frontend into static files
2. **Stage 2 (production)**: Python 3.13-slim serves both the FastAPI backend and the frontend SPA

The backend serves:
- API endpoints at `/api/*`
- Frontend SPA at `/*` (static files from the Vite build)

## Volumes

| Host Path | Container Path | Mode | Purpose |
|-----------|---------------|------|---------|
| `./config` | `/app/config` | read-only | YAML configuration profiles |
| `./var` | `/app/var` | read-write | SQLite DB, uploads, cache |

## Environment Variables

Key variables (set in `.env` or `docker-compose.yml`):

| Variable | Default | Description |
|----------|---------|-------------|
| `EYEX_LLM_MODE` | `disabled` | Set to `auto` if you have API keys configured |
| `EYEX_DATABASE_URL` | `sqlite:////app/var/storage/eyex.sqlite3` | Database connection |
| `EYEX_STORAGE_DIR` | `/app/var/storage` | File storage path |
| `EYEX_CONFIG_DIR` | `/app/config` | Configuration directory |
| `EYEX_ALLOW_REMOTE_ACCESS` | `true` (in compose) | Allow non-loopback access |

See `.env.example` for the full list of available variables.

## Common Operations

```bash
# Rebuild after code changes
docker compose up --build

# Run in background
docker compose up -d

# View logs
docker compose logs -f eyex

# Stop
docker compose down

# Reset database (destructive)
rm var/storage/eyex.sqlite3
docker compose up
```

## Notes

- **No GPU/OCR**: The main image does not include PaddleOCR, PyTorch, or DirectML dependencies. Those are too heavy (~5GB+) and should run as a separate sidecar service if needed.
- **Image size**: The production image is under 500MB.
- **Config changes**: Since `./config` is mounted read-only, edit config files on the host and restart the container.
- **Database migrations**: Alembic migrations run automatically on startup via `init_db()`.
