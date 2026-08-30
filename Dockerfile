# ── Stage 1: Build Vite frontend ─────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# VITE_ vars are baked into the JS bundle at build time — declare each as ARG
# so Railway passes them through from service variables to docker build.
ARG VITE_DEMO_MODE=false
ENV VITE_DEMO_MODE=$VITE_DEMO_MODE
ARG VITE_ENABLE_LOGIN_SHOWCASE=false
ENV VITE_ENABLE_LOGIN_SHOWCASE=$VITE_ENABLE_LOGIN_SHOWCASE
# Raise Vite/Node heap to 4 GB — Phase 4 added react-force-graph-2d which
# pulls in three.js (~38 MB) and inflates Vite's bundle-time working set.
# The default ~1.5 GB ceiling can OOM-kill the build on Railway's small
# builders without any error log surfacing to the deploy UI.
ENV NODE_OPTIONS=--max-old-space-size=4096
RUN npm run build

# ── Stage 2: Python backend + static frontend ─────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# System deps (needed by some Python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./

# Copy built frontend into backend/static/
COPY --from=frontend-builder /app/frontend/dist ./static

# Persistent data directory for SQLite (mount a Railway Volume at /data)
RUN mkdir -p /data

ENV HOST=0.0.0.0
ENV PORT=8000
ENV DATABASE_URL=sqlite:////data/bmg_capital.db

# ── COST-CUT 2026-08-30: glibc memory tuning (Railway $107 bill incident) ─────
# MALLOC_ARENA_MAX=2 — limits glibc's per-thread memory arenas to 2. Default
# is 8*num_cores which for a 2-vCPU container means 16 arenas, each pre-
# allocating memory. Cutting to 2 arenas saves ~200-800MB baseline RSS on
# a pandas-heavy long-running process.
# MALLOC_TRIM_THRESHOLD_=131072 — trims free chunks >128KB back to OS
# aggressively. Default is 128MB which is why RSS creeps for hours.
# These pair with the memory_janitor cron (calls malloc_trim(0) every 15min).
ENV MALLOC_ARENA_MAX=2
ENV MALLOC_TRIM_THRESHOLD_=131072
# PYTHONMALLOC=malloc — use glibc's malloc directly (default is pymalloc
# small-object allocator, which can't be trimmed). Pairs with MALLOC_ARENA_MAX.
ENV PYTHONMALLOC=malloc

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST} --port ${PORT}"]
