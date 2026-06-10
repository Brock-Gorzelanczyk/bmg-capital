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

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST} --port ${PORT}"]
