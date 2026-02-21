#!/usr/bin/env bash
set -euo pipefail

BASE_BACKEND="http://127.0.0.1:8000"
PASS=0
FAIL=0

check() {
  local label="$1"
  local url="$2"
  local result
  result=$(curl -fsS --max-time 10 "$url" 2>&1) && {
    echo "✅ $label"
    ((PASS++))
  } || {
    echo "❌ $label — FAILED (url: $url)"
    echo "   Error: $result"
    ((FAIL++))
  }
}

echo "=== Smoke Tests ==="

check "Health endpoint"       "$BASE_BACKEND/api/health"
check "Covered Call endpoint" "$BASE_BACKEND/api/scans/covered-call/aggressive"
check "PMCC endpoint"         "$BASE_BACKEND/api/scans/pmcc/aggressive"

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  echo "❌ Smoke tests FAILED — deployment may be broken"
  exit 1
fi

echo "=== All smoke tests passed ✅ ==="