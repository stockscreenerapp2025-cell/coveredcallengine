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
echo "[1/5] Checking requirements.txt..."
if grep -q "emergentintegrations" backend/requirements.txt; then
    sed -i '/emergentintegrations/d' backend/requirements.txt
    echo "  ✅ Removed emergentintegrations from requirements.txt"
else
    echo "  ✅ emergentintegrations not found (already clean)"
fi

# --------------------------------------------------
# 2. Fix health check endpoint in docker-compose files
# --------------------------------------------------
echo "[2/5] Fixing health check endpoints..."
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
echo "[3/5] Removing Emergent branding from frontend..."
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
# 4. Fix ajv dependency conflict in frontend
# --------------------------------------------------
echo "[4/5] Fixing frontend ajv dependency..."
if [ -f "frontend/package.json" ]; then
    cat > /tmp/fix_ajv.py << 'PYEOF'
import json

with open('frontend/package.json', 'r') as f:
    pkg = json.load(f)

if 'dependencies' not in pkg:
    pkg['dependencies'] = {}

# Force ajv v8 to fix ajv-keywords compatibility with Node 20
pkg['dependencies']['ajv'] = '^8.0.0'

with open('frontend/package.json', 'w') as f:
    json.dump(pkg, f, indent=2)

print('ajv dependency fixed')
PYEOF
    python3 /tmp/fix_ajv.py
    echo "  ✅ Fixed ajv dependency in package.json"

    # Remove package-lock.json to force clean install with fixed deps
    if [ -f "frontend/package-lock.json" ]; then
        rm frontend/package-lock.json
        echo "  ✅ Removed package-lock.json (will regenerate cleanly)"
    fi
fi

# --------------------------------------------------
# 5. Ensure .env files exist on server
# --------------------------------------------------
echo "[5/5] Checking environment files..."
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