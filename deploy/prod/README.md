# CCE Production Deployment

This folder contains everything needed to deploy CCE to production.

## Quick Start

```bash
# 1. Copy and configure environment
cp .env.example .env.production
nano .env.production  # Fill in your secrets

# 2. First-time deployment (gets SSL + starts services)
chmod +x deploy.sh
./deploy.sh first-run

# 3. Access your site
# https://cce.coveredcallengine.com
```

## Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Production orchestration |
| `backend.Dockerfile` | Gunicorn-based API server |
| `frontend.Dockerfile` | Multi-stage React build |
| `nginx/` | Reverse proxy + SSL config |
| `.env.example` | Environment template |
| `deploy.sh` | Deployment script |

## Architecture

```
Internet → Nginx (443/SSL) → /api/* → Backend (8000)
                           → /*     → Frontend (80)
                           ↓
                        MongoDB (internal)
```

## Commands

```bash
# Start services
docker compose up -d

# View logs
docker compose logs -f

# Rebuild and restart
docker compose up -d --build

# Stop everything
docker compose down

# Renew SSL (auto-runs via certbot container)
./deploy.sh ssl-only
```

## Security

- MongoDB: No public ports, internal network only
- SSL: Auto-renewed by Certbot container
- Secrets: Stored in `.env.production` (gitignored)
