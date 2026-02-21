# ============================================================
# Stage 1: Builder — install deps in isolated layer
# ============================================================
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ============================================================
# Stage 2: Production runtime image
# ============================================================
FROM python:3.12-slim AS production

# ✅ Install curl for healthcheck (VERY IMPORTANT)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --system appgroup && \
    useradd --system --gid appgroup --no-create-home appuser

WORKDIR /app

# Fix Python imports
ENV PYTHONPATH=/app/backend

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy backend code
COPY backend/ ./backend/

# Set permissions
RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["python","-m","uvicorn","server:app","--host","0.0.0.0","--port","8000","--workers","4","--loop","asyncio","--no-access-log"]
