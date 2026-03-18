#!/bin/bash
# Comprehensive Observability Stack Verification Script
# Verifies: Enrichment Service → MLflow → OTel Collector → Tempo → Kiali
#
# Usage: ./verify-observability-stack.sh [--detailed]

set -e

NAMESPACE="catalystlab-shared"
DETAILED=false

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
if [[ "$1" == "--detailed" ]]; then
    DETAILED=true
fi

function print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

function print_check() {
    echo -e "${YELLOW}[CHECK]${NC} $1"
}

function print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

function print_fail() {
    echo -e "${RED}[✗]${NC} $1"
}

function print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# =============================================================================
# 1. MLflow Enrichment Service Verification
# =============================================================================
print_header "1. MLflow Enrichment Service"

print_check "Checking enrichment service deployment..."
if kubectl get deployment mlflow-enrichment -n $NAMESPACE &>/dev/null; then
    READY=$(kubectl get deployment mlflow-enrichment -n $NAMESPACE -o jsonpath='{.status.readyReplicas}')
    if [[ "$READY" == "1" ]]; then
        print_success "Enrichment service is running (1/1 ready)"
    else
        print_fail "Enrichment service pods not ready ($READY/1)"
    fi
else
    print_fail "Enrichment service deployment not found"
fi

print_check "Checking enrichment service logs for activity..."
ENRICHMENT_POD=$(kubectl get pods -n $NAMESPACE -l app=mlflow-enrichment -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [[ -n "$ENRICHMENT_POD" ]]; then
    ENRICHED_COUNT=$(kubectl logs -n $NAMESPACE $ENRICHMENT_POD --tail=100 | grep -c "Successfully enriched trace" || echo "0")
    if [[ "$ENRICHED_COUNT" -gt 0 ]]; then
        print_success "Enrichment service has enriched $ENRICHED_COUNT traces recently"
    else
        print_info "No recent enrichment activity (may be normal if no new traces)"
    fi

    if $DETAILED; then
        print_info "Recent log entries:"
        kubectl logs -n $NAMESPACE $ENRICHMENT_POD --tail=10
    fi
else
    print_fail "Cannot find enrichment service pod"
fi

print_check "Verifying enrichment service database connectivity..."
if [[ -n "$ENRICHMENT_POD" ]]; then
    DB_ERRORS=$(kubectl logs -n $NAMESPACE $ENRICHMENT_POD --tail=100 | grep -ic "database" | grep -ic "error" || echo "0")
    if [[ "$DB_ERRORS" -eq 0 ]]; then
        print_success "No database connection errors"
    else
        print_fail "Database connection issues detected ($DB_ERRORS errors)"
    fi
fi

# =============================================================================
# 2. MLflow Field Population Verification
# =============================================================================
print_header "2. MLflow Field Population"

print_check "Checking MLflow database for enriched fields..."
POSTGRES_POD=$(kubectl get pods -n $NAMESPACE -l cnpg.io/cluster=pgvector-cluster,role=primary -o jsonpath='{.items[0].metadata.name}')

if [[ -n "$POSTGRES_POD" ]]; then
    # Check trace_tags table
    print_check "Verifying trace_tags table..."
    TRACE_TAGS_COUNT=$(kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -t -c "SELECT COUNT(*) FROM trace_tags WHERE key IN ('mlflow.user', 'mlflow.session', 'mlflow.traceName', 'mlflow.source.name', 'mlflow.source.type');" 2>/dev/null | tr -d ' ')

    if [[ "$TRACE_TAGS_COUNT" -gt 0 ]]; then
        print_success "trace_tags table has $TRACE_TAGS_COUNT enriched entries"

        if $DETAILED; then
            print_info "Sample trace_tags entries:"
            kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -c "SELECT key, value, request_id FROM trace_tags WHERE key IN ('mlflow.user', 'mlflow.source.name') LIMIT 5;"
        fi
    else
        print_fail "No enriched trace_tags found"
    fi

    # Check trace_info table
    print_check "Verifying trace_info table (request/response previews)..."
    TRACE_INFO_COUNT=$(kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -t -c "SELECT COUNT(*) FROM trace_info WHERE request_preview IS NOT NULL AND response_preview IS NOT NULL;" 2>/dev/null | tr -d ' ')

    if [[ "$TRACE_INFO_COUNT" -gt 0 ]]; then
        print_success "trace_info table has $TRACE_INFO_COUNT traces with previews"

        if $DETAILED; then
            print_info "Sample trace_info entry:"
            kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -c "SELECT request_id, LEFT(request_preview, 50) as request_preview_sample, LEFT(response_preview, 50) as response_preview_sample FROM trace_info WHERE request_preview IS NOT NULL LIMIT 3;"
        fi
    else
        print_fail "No traces with request/response previews found"
    fi

    # Check trace_request_metadata table
    print_check "Verifying trace_request_metadata table..."
    METADATA_COUNT=$(kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -t -c "SELECT COUNT(*) FROM trace_request_metadata WHERE key IN ('enrichment_source', 'model', 'operation');" 2>/dev/null | tr -d ' ')

    if [[ "$METADATA_COUNT" -gt 0 ]]; then
        print_success "trace_request_metadata table has $METADATA_COUNT enriched entries"

        if $DETAILED; then
            print_info "Sample metadata entries:"
            kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -c "SELECT key, value, request_id FROM trace_request_metadata WHERE key IN ('enrichment_source', 'model') LIMIT 5;"
        fi
    else
        print_fail "No enriched metadata found"
    fi

    # Check token usage fields
    print_check "Verifying token usage fields..."
    TOKEN_COUNT=$(kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -t -c "SELECT COUNT(*) FROM trace_tags WHERE key IN ('mlflow.promptTokens', 'mlflow.completionTokens', 'mlflow.totalTokens');" 2>/dev/null | tr -d ' ')

    if [[ "$TOKEN_COUNT" -gt 0 ]]; then
        print_success "Token usage fields populated ($TOKEN_COUNT entries)"

        if $DETAILED; then
            print_info "Sample token usage:"
            kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -c "SELECT key, value FROM trace_tags WHERE key IN ('mlflow.promptTokens', 'mlflow.completionTokens', 'mlflow.totalTokens') LIMIT 6;"
        fi
    else
        print_info "No token usage data (may be normal for non-GenAI traces)"
    fi
else
    print_fail "Cannot find PostgreSQL pod"
fi

# =============================================================================
# 3. VLLM → OTel Collector Data Flow
# =============================================================================
print_header "3. VLLM → OTel Collector Data Flow"

print_check "Checking OTel Collector deployment..."
if kubectl get deployment otel-collector -n $NAMESPACE &>/dev/null; then
    READY=$(kubectl get deployment otel-collector -n $NAMESPACE -o jsonpath='{.status.readyReplicas}')
    if [[ "$READY" == "1" ]]; then
        print_success "OTel Collector is running (1/1 ready)"
    else
        print_fail "OTel Collector pods not ready ($READY/1)"
    fi
else
    print_fail "OTel Collector deployment not found"
fi

print_check "Checking for vLLM traces in spans table..."
if [[ -n "$POSTGRES_POD" ]]; then
    VLLM_SPAN_COUNT=$(kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -t -c "SELECT COUNT(*) FROM spans WHERE content::json->'attributes'->>'peer.service' = 'vllm';" 2>/dev/null | tr -d ' ')

    if [[ "$VLLM_SPAN_COUNT" -gt 0 ]]; then
        print_success "Found $VLLM_SPAN_COUNT vLLM spans in MLflow database"

        if $DETAILED; then
            print_info "Sample vLLM spans:"
            kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -c "SELECT name, type, to_timestamp(start_time_unix_nano/1000000000.0) as span_time FROM spans WHERE content::json->'attributes'->>'peer.service' = 'vllm' ORDER BY start_time_unix_nano DESC LIMIT 5;"
        fi
    else
        print_fail "No vLLM spans found (may indicate instrumentation issue)"
    fi

    # Check for CHAT_MODEL spans (GenAI semantic conventions)
    print_check "Checking for CHAT_MODEL spans (GenAI operations)..."
    CHAT_MODEL_COUNT=$(kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -t -c "SELECT COUNT(*) FROM spans WHERE type = 'CHAT_MODEL';" 2>/dev/null | tr -d ' ')

    if [[ "$CHAT_MODEL_COUNT" -gt 0 ]]; then
        print_success "Found $CHAT_MODEL_COUNT CHAT_MODEL spans"

        if $DETAILED; then
            print_info "Sample CHAT_MODEL spans:"
            kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -c "SELECT name, content::json->'attributes'->>'gen_ai.request.model' as model, content::json->'attributes'->>'gen_ai.usage.input_tokens' as input_tokens FROM spans WHERE type = 'CHAT_MODEL' LIMIT 3;"
        fi
    else
        print_fail "No CHAT_MODEL spans found"
    fi
fi

print_check "Checking OTel Collector logs for vLLM exports..."
OTEL_POD=$(kubectl get pods -n $NAMESPACE -l app=otel-collector -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [[ -n "$OTEL_POD" ]]; then
    OTEL_EXPORTS=$(kubectl logs -n $NAMESPACE $OTEL_POD --tail=100 2>/dev/null | grep -c "otlp" || echo "0")
    if [[ "$OTEL_EXPORTS" -gt 0 ]]; then
        print_success "OTel Collector is exporting traces ($OTEL_EXPORTS recent OTLP exports)"
    else
        print_info "No recent OTLP export activity in logs"
    fi

    if $DETAILED; then
        print_info "Recent OTel Collector logs:"
        kubectl logs -n $NAMESPACE $OTEL_POD --tail=10
    fi
else
    print_fail "Cannot find OTel Collector pod"
fi

# =============================================================================
# 4. LlamaStack → OTel Collector Data Flow
# =============================================================================
print_header "4. LlamaStack → OTel Collector Data Flow"

print_check "Checking LlamaStack deployment..."
if kubectl get deployment llamastack -n $NAMESPACE &>/dev/null; then
    READY=$(kubectl get deployment llamastack -n $NAMESPACE -o jsonpath='{.status.readyReplicas}')
    if [[ "$READY" == "1" ]]; then
        print_success "LlamaStack is running (1/1 ready)"
    else
        print_fail "LlamaStack pods not ready ($READY/1)"
    fi
else
    print_fail "LlamaStack deployment not found"
fi

print_check "Verifying LlamaStack OTEL_EXPORTER_OTLP_ENDPOINT configuration..."
OTEL_ENDPOINT=$(kubectl get deployment llamastack -n $NAMESPACE -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="OTEL_EXPORTER_OTLP_ENDPOINT")].value}' 2>/dev/null)
if [[ -n "$OTEL_ENDPOINT" ]]; then
    print_success "LlamaStack OTEL endpoint configured: $OTEL_ENDPOINT"
else
    print_fail "LlamaStack OTEL_EXPORTER_OTLP_ENDPOINT not configured"
fi

print_check "Checking for LlamaStack traces in spans table..."
if [[ -n "$POSTGRES_POD" ]]; then
    LLAMASTACK_SPAN_COUNT=$(kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -t -c "SELECT COUNT(*) FROM spans WHERE name LIKE '%llamastack%' OR name LIKE '%POST%' OR name LIKE '%chat%';" 2>/dev/null | tr -d ' ')

    if [[ "$LLAMASTACK_SPAN_COUNT" -gt 0 ]]; then
        print_success "Found $LLAMASTACK_SPAN_COUNT LlamaStack-related spans"

        if $DETAILED; then
            print_info "Sample LlamaStack spans:"
            kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -c "SELECT name, type, to_timestamp(start_time_unix_nano/1000000000.0) as span_time FROM spans WHERE name LIKE '%POST%' OR name LIKE '%chat%' ORDER BY start_time_unix_nano DESC LIMIT 5;"
        fi
    else
        print_fail "No LlamaStack spans found"
    fi
fi

print_check "Checking LlamaStack logs for OTEL activity..."
LLAMASTACK_POD=$(kubectl get pods -n $NAMESPACE -l app=llamastack -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [[ -n "$LLAMASTACK_POD" ]]; then
    OTEL_LOGS=$(kubectl logs -n $NAMESPACE $LLAMASTACK_POD --tail=100 2>/dev/null | grep -ic "otel\|trace\|span" || echo "0")
    if [[ "$OTEL_LOGS" -gt 0 ]]; then
        print_success "LlamaStack logs show OTEL activity ($OTEL_LOGS mentions)"
    else
        print_info "No OTEL activity in recent logs"
    fi

    if $DETAILED; then
        print_info "Recent LlamaStack logs:"
        kubectl logs -n $NAMESPACE $LLAMASTACK_POD --tail=10
    fi
else
    print_fail "Cannot find LlamaStack pod"
fi

# =============================================================================
# 5. Tempo Span Capture Verification
# =============================================================================
print_header "5. Tempo Span Capture"

print_check "Checking Tempo distributor deployment..."
if kubectl get deployment tempo-distributor -n $NAMESPACE &>/dev/null; then
    READY=$(kubectl get deployment tempo-distributor -n $NAMESPACE -o jsonpath='{.status.readyReplicas}')
    if [[ "$READY" == "1" ]]; then
        print_success "Tempo distributor is running (1/1 ready)"
    else
        print_fail "Tempo distributor pods not ready ($READY/1)"
    fi
else
    print_fail "Tempo distributor deployment not found"
fi

print_check "Checking Tempo ingester statefulset..."
if kubectl get statefulset tempo-ingester -n $NAMESPACE &>/dev/null; then
    READY=$(kubectl get statefulset tempo-ingester -n $NAMESPACE -o jsonpath='{.status.readyReplicas}')
    if [[ "$READY" == "1" ]]; then
        print_success "Tempo ingester is running (1/1 ready)"
    else
        print_fail "Tempo ingester pods not ready ($READY/1)"
    fi
else
    print_fail "Tempo ingester statefulset not found"
fi

print_check "Verifying OTel Collector → Tempo exporter configuration..."
OTEL_CM=$(kubectl get configmap otel-collector-config -n $NAMESPACE -o yaml 2>/dev/null | grep -A 2 "otlp_grpc/tempo" || echo "")
if [[ -n "$OTEL_CM" ]]; then
    print_success "OTel Collector has Tempo exporter configured"

    if $DETAILED; then
        print_info "Tempo exporter config:"
        echo "$OTEL_CM"
    fi
else
    print_fail "Tempo exporter not configured in OTel Collector"
fi

print_check "Checking Tempo distributor logs for trace ingestion..."
TEMPO_DIST_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/component=distributor,app.kubernetes.io/instance=tempo -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [[ -n "$TEMPO_DIST_POD" ]]; then
    TEMPO_RECEIVES=$(kubectl logs -n $NAMESPACE $TEMPO_DIST_POD --tail=100 2>/dev/null | grep -ic "pusher\|batch\|span" || echo "0")
    if [[ "$TEMPO_RECEIVES" -gt 0 ]]; then
        print_success "Tempo distributor is processing traces ($TEMPO_RECEIVES log entries)"
    else
        print_info "No recent trace ingestion activity in Tempo distributor logs"
    fi

    if $DETAILED; then
        print_info "Recent Tempo distributor logs:"
        kubectl logs -n $NAMESPACE $TEMPO_DIST_POD --tail=10
    fi
else
    print_fail "Cannot find Tempo distributor pod"
fi

print_check "Checking Tempo ingester logs for trace storage..."
TEMPO_ING_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/component=ingester,app.kubernetes.io/instance=tempo -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [[ -n "$TEMPO_ING_POD" ]]; then
    TEMPO_BLOCKS=$(kubectl logs -n $NAMESPACE $TEMPO_ING_POD --tail=100 2>/dev/null | grep -ic "block\|flushed\|wal" || echo "0")
    if [[ "$TEMPO_BLOCKS" -gt 0 ]]; then
        print_success "Tempo ingester is writing traces to storage ($TEMPO_BLOCKS log entries)"
    else
        print_info "No recent trace storage activity in Tempo ingester logs"
    fi

    if $DETAILED; then
        print_info "Recent Tempo ingester logs:"
        kubectl logs -n $NAMESPACE $TEMPO_ING_POD --tail=10
    fi
else
    print_fail "Cannot find Tempo ingester pod"
fi

# =============================================================================
# 6. Kiali Integration Verification
# =============================================================================
print_header "6. Kiali Integration"

print_check "Checking Kiali deployment..."
if kubectl get deployment kiali -n istio-system &>/dev/null; then
    READY=$(kubectl get deployment kiali -n istio-system -o jsonpath='{.status.readyReplicas}')
    if [[ "$READY" == "1" ]]; then
        print_success "Kiali is running (1/1 ready)"
    else
        print_fail "Kiali pods not ready ($READY/1)"
    fi
else
    print_fail "Kiali deployment not found in istio-system namespace"
fi

print_check "Verifying Kiali Tempo integration configuration..."
KIALI_TEMPO_CONFIG=$(kubectl get configmap kiali -n istio-system -o yaml 2>/dev/null | grep -A 5 "tracing:" | grep "provider: tempo" || echo "")
if [[ -n "$KIALI_TEMPO_CONFIG" ]]; then
    print_success "Kiali configured with Tempo provider"

    if $DETAILED; then
        print_info "Kiali tracing config:"
        kubectl get configmap kiali -n istio-system -o yaml | grep -A 10 "tracing:"
    fi
else
    print_fail "Kiali not configured with Tempo provider"
fi

print_check "Testing Kiali → Tempo connectivity..."
KIALI_POD=$(kubectl get pods -n istio-system -l app.kubernetes.io/name=kiali -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [[ -n "$KIALI_POD" ]]; then
    TEMPO_CONN=$(kubectl exec -n istio-system $KIALI_POD -- curl -s -o /dev/null -w "%{http_code}" http://tempo-query-frontend.catalystlab-shared.svc.cluster.local:3200 2>/dev/null || echo "000")
    if [[ "$TEMPO_CONN" == "200" ]] || [[ "$TEMPO_CONN" == "404" ]]; then
        print_success "Kiali can reach Tempo query frontend (HTTP $TEMPO_CONN)"
    else
        print_fail "Kiali cannot reach Tempo query frontend (HTTP $TEMPO_CONN)"
    fi
else
    print_fail "Cannot find Kiali pod"
fi

print_check "Verifying Kiali service graph has MLflow components..."
if [[ -n "$KIALI_POD" ]]; then
    # Check if Kiali can see mlflow service
    KIALI_SERVICES=$(kubectl exec -n istio-system $KIALI_POD -- curl -s "http://localhost:20001/api/namespaces/$NAMESPACE/services" 2>/dev/null | grep -c "mlflow" || echo "0")
    if [[ "$KIALI_SERVICES" -gt 0 ]]; then
        print_success "Kiali sees MLflow service in $NAMESPACE namespace"
    else
        print_info "MLflow service not visible in Kiali (check sidecar injection)"
    fi
fi

# =============================================================================
# Summary
# =============================================================================
print_header "Verification Summary"

echo ""
print_info "Components Checked:"
echo "  1. ✓ MLflow Enrichment Service"
echo "  2. ✓ MLflow Database Field Population"
echo "  3. ✓ VLLM → OTel Collector Data Flow"
echo "  4. ✓ LlamaStack → OTel Collector Data Flow"
echo "  5. ✓ Tempo Trace Capture"
echo "  6. ✓ Kiali Integration"
echo ""
print_info "For detailed output, run: $0 --detailed"
echo ""
