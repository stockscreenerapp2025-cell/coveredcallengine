# ============================================================
# Stage 1: Builder — install deps in isolated layer
# ============================================================
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (layer cache optimization)
COPY backend/requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt

# ============================================================
# Stage 2: Production runtime image
# ============================================================
FROM python:3.12-slim AS production

# Security: run as non-root user
RUN groupadd --system appgroup && \
    useradd --system --gid appgroup --no-create-home appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY backend/ ./backend/

# Ensure .env is NOT baked in — use runtime secrets/env vars
# (add .env to .dockerignore)

RUN chown -R appuser:appgroup /app
USER appuser

# Expose backend port
EXPOSE 8000

# Health check — adjust path to your actual health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Production server: Uvicorn with Gunicorn workers
# Adjust 'backend.server:app' to match your actual FastAPI app entrypoint
CMD ["python", "-m", "uvicorn", "backend.server:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--loop", "uvloop", \
     "--no-access-log"]
