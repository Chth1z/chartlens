# ─── Stage 1: Build frontend ───────────────────────────────────────────────────
FROM node:24-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# ─── Stage 2: Production backend ──────────────────────────────────────────────
FROM python:3.13-slim AS production

WORKDIR /app

# Install system deps needed by some Python packages (sqlite, etc.)
RUN apt-get update && \
    apt-get install -y --no-install-recommends sqlite3 && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend source
COPY backend/ /app/backend/

# Copy built frontend from stage 1
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

# Copy default config (can be overridden via volume mount)
COPY config/ /app/config/

# Create var directory for runtime state
RUN mkdir -p /app/var/storage

# Environment defaults
ENV EYEX_CONFIG_DIR=/app/config \
    EYEX_STORAGE_DIR=/app/var/storage \
    EYEX_DATABASE_URL=sqlite:////app/var/storage/eyex.sqlite3 \
    EYEX_LLM_MODE=disabled \
    EYEX_ALLOW_REMOTE_ACCESS=false

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
WORKDIR /app/backend
