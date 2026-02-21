#!/usr/bin/env bash
set -euo pipefail

echo "=== Normalize: Emergent → VPS ==="

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# 1) Remove emergentintegrations from requirements.txt (not on PyPI)
if grep -q "emergentintegrations" backend/requirements.txt 2>/dev/null; then
  sed -i '/emergentintegrations/d' backend/requirements.txt
  echo "✅ Removed emergentintegrations from requirements.txt"
else
  echo "✅ emergentintegrations not present — nothing to remove"
fi

# 2) Fix health check endpoint (Emergent uses /health, VPS needs /api/health)
for f in docker/docker-compose.prod.yml docker/docker-compose.test.yml; do
  if grep -q 'localhost:8000/health"' "$f" 2>/dev/null; then
    sed -i 's|localhost:8000/health"|localhost:8000/api/health"|g' "$f"
    echo "✅ Fixed health endpoint in $f"
  fi
done

# 3) Ensure .env files exist on VPS (fail loudly if missing)
if [[ ! -f ".env.production" ]]; then
  echo "ERROR: .env.production missing on VPS. Create it before deploying."
  exit 1
fi
if [[ ! -f ".env.test" ]]; then
  echo "ERROR: .env.test missing on VPS. Create it before deploying."
  exit 1
fi

echo "=== Normalization complete ✅ ==="