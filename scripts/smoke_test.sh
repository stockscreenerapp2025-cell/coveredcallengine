#!/usr/bin/env bash
set -euo pipefail

echo "================================================"
echo "  Running smoke tests..."
echo "================================================"

# Wait for containers to be fully ready
echo "Waiting 30 seconds for containers to start..."
sleep 30

BACKEND_URL="http://localhost:8000"
PASS=0
FAIL=0

# --------------------------------------------------
# Test 1: Health endpoint
# --------------------------------------------------
echo "[1/3] Testing /api/health..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$BACKEND_URL/api/health" 2>/dev/null || echo "000")
if [ "$RESPONSE" = "200" ]; then
    echo "  ✅ Health endpoint OK (HTTP 200)"
    PASS=$((PASS + 1))
else
    echo "  ❌ Health endpoint FAILED (HTTP $RESPONSE)"
    FAIL=$((FAIL + 1))
fi

# --------------------------------------------------
# Test 2: Backend API docs accessible
# --------------------------------------------------
echo "[2/3] Testing backend API..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$BACKEND_URL/docs" 2>/dev/null || echo "000")
if [ "$RESPONSE" = "200" ]; then
    echo "  ✅ Backend API accessible (HTTP 200)"
    PASS=$((PASS + 1))
else
    echo "  ❌ Backend API FAILED (HTTP $RESPONSE)"
    FAIL=$((FAIL + 1))
fi

# --------------------------------------------------
# Test 3: Frontend accessible
# --------------------------------------------------
echo "[3/3] Testing frontend..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8080/" 2>/dev/null || echo "000")
if [ "$RESPONSE" = "200" ]; then
    echo "  ✅ Frontend accessible (HTTP 200)"
    PASS=$((PASS + 1))
else
    echo "  ❌ Frontend FAILED (HTTP $RESPONSE)"
    FAIL=$((FAIL + 1))
fi

# --------------------------------------------------
# Summary
# --------------------------------------------------
echo ""
echo "================================================"
echo "  Smoke test results: $PASS passed, $FAIL failed"
echo "================================================"

if [ "$FAIL" -gt 0 ]; then
    echo "  ⚠️  Some tests failed but deployment continues"
    echo "  Check logs with: docker logs cce_backend --tail 50"
fi

echo "  Smoke tests complete ✅"