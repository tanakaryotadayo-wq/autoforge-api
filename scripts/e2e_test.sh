#!/usr/bin/env bash
# AutoForge E2E Test — run after `docker compose up -d`
# Usage: bash scripts/e2e_test.sh

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8698}"
PASS=0
FAIL=0

green() { printf "\033[32m✅ %s\033[0m\n" "$1"; }
red()   { printf "\033[31m❌ %s\033[0m\n" "$1"; }

test_endpoint() {
    local name="$1" method="$2" path="$3" expected_status="$4"
    shift 4
    local extra_args=("$@")

    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "${extra_args[@]}" "${BASE_URL}${path}")

    if [ "$status" = "$expected_status" ]; then
        green "$name → $status"
        PASS=$((PASS + 1))
    else
        red "$name → expected $expected_status, got $status"
        FAIL=$((FAIL + 1))
    fi
}

echo "🧪 AutoForge E2E Tests"
echo "   Target: $BASE_URL"
echo ""

# 1. Health check
test_endpoint "GET /health" GET "/health" "200"

# 2. Metrics
test_endpoint "GET /metrics" GET "/metrics" "200"

# 3. Domains list
test_endpoint "GET /v1/domains" GET "/v1/domains" "200"

# 4. Login (invalid)
test_endpoint "POST /token (invalid)" POST "/token?username=bad&password=bad" "401"

# 5. Login (admin)
echo ""
echo "🔑 Getting admin token..."
TOKEN=$(curl -s -X POST "${BASE_URL}/token?username=admin&password=admin123" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")

if [ -n "$TOKEN" ]; then
    green "Admin login successful"
    PASS=$((PASS + 1))

    # 6. Learn
    test_endpoint "POST /v1/learn" POST "/v1/learn" "200" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $TOKEN" \
        -H "X-Tenant-ID: e2e-test" \
        -d '{"content": "E2Eテスト知識データ: 広告CPAの平均は5000円", "category": "test"}'

    # 7. Query
    test_endpoint "POST /v1/query" POST "/v1/query" "200" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $TOKEN" \
        -H "X-Tenant-ID: e2e-test" \
        -d '{"query": "CPAの平均", "top_k": 3}'

    # 8. Stats
    test_endpoint "GET /v1/stats" GET "/v1/stats" "200" \
        -H "Authorization: Bearer $TOKEN" \
        -H "X-Tenant-ID: e2e-test"

    # 9. Proposals History
    test_endpoint "GET /v1/proposals/history" GET "/v1/proposals/history?limit=5" "200" \
        -H "Authorization: Bearer $TOKEN" \
        -H "X-Tenant-ID: e2e-test"

    # 10. Propose (requires LLM API key — may fail gracefully)
    echo ""
    echo "💡 POST /v1/propose (LLM-dependent, may 500 without API key)"
    PROPOSE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $TOKEN" \
        -H "X-Tenant-ID: e2e-test" \
        -d '{"user_data": {"campaign": "test", "cpa": 10000}, "domain": "ad_optimization"}' \
        "${BASE_URL}/v1/propose")

    if [ "$PROPOSE_STATUS" = "200" ]; then
        green "POST /v1/propose → 200 (LLM working)"
        PASS=$((PASS + 1))
    elif [ "$PROPOSE_STATUS" = "500" ]; then
        echo "   ⚠️  POST /v1/propose → 500 (expected without valid API key)"
    else
        red "POST /v1/propose → unexpected $PROPOSE_STATUS"
        FAIL=$((FAIL + 1))
    fi
else
    red "Admin login failed — skipping authenticated tests"
    FAIL=$((FAIL + 1))
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   Results: ✅ $PASS passed, ❌ $FAIL failed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
