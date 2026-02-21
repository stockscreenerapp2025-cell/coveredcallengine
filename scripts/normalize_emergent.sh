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
echo "[1/4] Checking requirements.txt..."
if grep -q "emergentintegrations" backend/requirements.txt; then
    sed -i '/emergentintegrations/d' backend/requirements.txt
    echo "  ✅ Removed emergentintegrations from requirements.txt"
else
    echo "  ✅ emergentintegrations not found (already clean)"
fi

# --------------------------------------------------
# 2. Fix health check endpoint in docker-compose files
# --------------------------------------------------
echo "[2/4] Fixing health check endpoints..."
if grep -q "localhost:8000/health\"" docker/docker-compose.prod.yml 2>/dev/null; then
    sed -i 's|http://localhost:8000/health|http://localhost:8000/api/health|g' docker/docker-compose.prod.yml
    echo "  ✅ Fixed health endpoint in docker-compose.prod.yml"
else
    echo "  ✅ Health endpoint already correct in prod"
fi

if grep -q "localhost:8000/health\"" docker/docker-compose.test.yml 2>/dev/null; then
    sed -i 's|http://localhost:8000/health|http://localhost:8000/api/health|g' docker/docker-compose.test.yml
    echo "  ✅ Fixed health endpoint in docker-compose.test.yml"
else
    echo "  ✅ Health endpoint already correct in test"
fi

# --------------------------------------------------
# 3. Remove Emergent branding from index.html
# --------------------------------------------------
echo "[3/4] Removing Emergent branding from frontend..."
INDEX_HTML="frontend/public/index.html"

if grep -q "emergent" "$INDEX_HTML" 2>/dev/null; then
    # Fix title
    sed -i 's|<title>Emergent.*</title>|<title>Covered Call Engine</title>|g' "$INDEX_HTML"
    
    # Remove emergent-main.js script tag
    sed -i '/emergent-main\.js/d' "$INDEX_HTML"
    
    # Remove emergent badge anchor tag (multi-line removal)
    python3 -c "
import re, sys
with open('$INDEX_HTML', 'r') as f:
    content = f.read()

# Remove emergent badge
content = re.sub(r'<a[^>]*id=[\"'"'"']emergent-badge[\"'"'"'][^>]*>.*?</a>', '', content, flags=re.DOTALL)

# Remove emergent scripts block
content = re.sub(r'<script>\s*//\s*Only load visual edit scripts.*?</script>', '', content, flags=re.DOTALL)

# Remove posthog analytics
content = re.sub(r'<script>\s*!\(function.*?posthog\.init.*?</script>', '', content, flags=re.DOTALL)

# Fix meta description
content = content.replace('A product of emergent.sh', 'Professional-grade options screening engine')

with open('$INDEX_HTML', 'w') as f:
    f.write(content)
print('Done')
"
    echo "  ✅ Removed Emergent branding from index.html"
else
    echo "  ✅ No Emergent branding found (already clean)"
fi

# --------------------------------------------------
# 4. Ensure .env files exist on server
# --------------------------------------------------
echo "[4/4] Checking environment files..."
if [ ! -f "$ROOT_DIR/.env.production" ]; then
    echo "  ❌ ERROR: .env.production not found at $ROOT_DIR/.env.production"
    echo "     Please create this file on the server before deploying"
    exit 1
else
    echo "  ✅ .env.production exists"
fi

if [ ! -f "$ROOT_DIR/.env.test" ]; then
    echo "  ❌ ERROR: .env.test not found at $ROOT_DIR/.env.test"
    echo "     Please create this file on the server before deploying"
    exit 1
else
    echo "  ✅ .env.test exists"
fi

echo ""
echo "================================================"
echo "  Normalization complete ✅"
echo "================================================"