#!/usr/bin/env bash
set -euo pipefail

echo "================================================"
echo "  Normalizing Emergent code for VPS deployment"
echo "================================================"

ROOT_DIR="/opt/covered-call-engine"
cd "$ROOT_DIR"

# --------------------------------------------------
# 1. Remove emergentintegrations from requirements.txt
# --------------------------------------------------
echo "[1/6] Checking requirements.txt..."
if grep -q "emergentintegrations" backend/requirements.txt; then
    sed -i '/emergentintegrations/d' backend/requirements.txt
    echo "  ✅ Removed emergentintegrations from requirements.txt"
else
    echo "  ✅ emergentintegrations not found (already clean)"
fi

# --------------------------------------------------
# 2. Fix health check endpoint in docker-compose files
# --------------------------------------------------
echo "[2/6] Fixing health check endpoints..."
if grep -q 'localhost:8000/health"' docker/docker-compose.prod.yml 2>/dev/null; then
    sed -i 's|http://localhost:8000/health|http://localhost:8000/api/health|g' docker/docker-compose.prod.yml
    echo "  ✅ Fixed health endpoint in docker-compose.prod.yml"
else
    echo "  ✅ Health endpoint already correct in prod"
fi

if grep -q 'localhost:8000/health"' docker/docker-compose.test.yml 2>/dev/null; then
    sed -i 's|http://localhost:8000/health|http://localhost:8000/api/health|g' docker/docker-compose.test.yml
    echo "  ✅ Fixed health endpoint in docker-compose.test.yml"
else
    echo "  ✅ Health endpoint already correct in test"
fi

# --------------------------------------------------
# 3. Remove Emergent branding from index.html
# --------------------------------------------------
echo "[3/6] Removing Emergent branding from frontend..."
INDEX_HTML="frontend/public/index.html"

if grep -qi "emergent" "$INDEX_HTML" 2>/dev/null; then
    cat > /tmp/fix_index.py << 'PYEOF'
import re

with open('frontend/public/index.html', 'r') as f:
    content = f.read()

content = re.sub(r'<title>Emergent[^<]*</title>', '<title>Covered Call Engine</title>', content)
content = re.sub(r'<script[^>]*emergent-main\.js[^>]*></script>\s*', '', content)
content = re.sub(r'<a[^>]*id="emergent-badge"[^>]*>.*?</a>', '', content, flags=re.DOTALL)
content = re.sub(r'<!--\s*These two scripts.*?-->\s*<script>\s*// Only load visual edit.*?</script>', '', content, flags=re.DOTALL)
content = re.sub(r'<script>\s*!\(function \(t, e\).*?posthog\.init.*?</script>', '', content, flags=re.DOTALL)
content = content.replace('A product of emergent.sh', 'Professional-grade options screening engine')

with open('frontend/public/index.html', 'w') as f:
    f.write(content)

print('Emergent branding removed successfully')
PYEOF
    python3 /tmp/fix_index.py
    echo "  ✅ Removed Emergent branding from index.html"
else
    echo "  ✅ No Emergent branding found (already clean)"
fi

# --------------------------------------------------
# 4. Fix frontend Dockerfile - downgrade Node 20 to Node 18
#    (Node 20 breaks ajv-keywords used by react-scripts/craco)
# --------------------------------------------------
echo "[4/6] Fixing frontend Dockerfile Node version..."
FRONTEND_DOCKERFILE="frontend/Dockerfile"
if grep -q "node:20" "$FRONTEND_DOCKERFILE" 2>/dev/null; then
    sed -i 's|node:20-alpine|node:18-alpine|g' "$FRONTEND_DOCKERFILE"
    sed -i 's|node:20|node:18|g' "$FRONTEND_DOCKERFILE"
    echo "  ✅ Downgraded Node 20 → Node 18 in frontend Dockerfile"
else
    echo "  ✅ Frontend Dockerfile Node version already correct"
fi

# --------------------------------------------------
# 5. Fix frontend API URL - remove undefined REACT_APP_BACKEND_URL
#    (Emergent sets this to an env var that doesn't exist on VPS)
# --------------------------------------------------
echo "[5/6] Fixing frontend API base URL..."
API_JS="frontend/src/lib/api.js"
if grep -q "process.env.REACT_APP_BACKEND_URL" "$API_JS" 2>/dev/null; then
    cat > /tmp/fix_api.py << 'PYEOF'
with open('frontend/src/lib/api.js', 'r') as f:
    content = f.read()

content = content.replace(
    'const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;',
    'const BACKEND_URL = "";  // Use relative URL - same domain'
)

with open('frontend/src/lib/api.js', 'w') as f:
    f.write(content)

print('api.js fixed')
PYEOF
    python3 /tmp/fix_api.py
    echo "  ✅ Fixed API base URL to use relative path"
else
    echo "  ✅ API base URL already correct"
fi

# --------------------------------------------------
# 6. Ensure .env files exist on server
# --------------------------------------------------
echo "[6/6] Checking environment files..."
if [ ! -f "$ROOT_DIR/.env.production" ]; then
    echo "  ❌ ERROR: .env.production not found"
    exit 1
else
    echo "  ✅ .env.production exists"
fi

if [ ! -f "$ROOT_DIR/.env.test" ]; then
    echo "  ❌ ERROR: .env.test not found"
    exit 1
else
    echo "  ✅ .env.test exists"
fi

echo ""
echo "================================================"
echo "  Normalization complete ✅"
echo "================================================"