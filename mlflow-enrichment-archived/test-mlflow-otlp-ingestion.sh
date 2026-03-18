#!/bin/bash
# Test MLflow OTLP Ingestion - Does MLflow auto-populate trace_tags/trace_info?
#
# This script sends a test trace with mlflow.* attributes and checks if MLflow
# automatically populates the UI tables or if we need the enrichment service.

set -e

NAMESPACE="catalystlab-shared"
POSTGRES_POD=$(kubectl get pods -n $NAMESPACE -l cnpg.io/cluster=pgvector-cluster,role=primary -o jsonpath='{.items[0].metadata.name}')
OTEL_COLLECTOR_SVC="otel-collector.catalystlab-shared.svc.cluster.local:4318"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}MLflow OTLP Ingestion Test${NC}"
echo -e "${BLUE}======================================${NC}\n"

# Generate unique trace ID
TRACE_ID="00000000000000000000000000$(date +%s)"
SPAN_ID="0000000000$(date +%s)"
TRACE_ID_SHORT="tr-$(date +%s)-test"

echo -e "${YELLOW}[1/5]${NC} Generating test trace with mlflow.* attributes..."

# Create test span payload with all mlflow.* attributes we want to test
# This simulates what OTel Collector transform processor adds
cat > /tmp/test-trace.json << EOF
{
  "resourceSpans": [{
    "resource": {
      "attributes": [
        {"key": "service.name", "value": {"stringValue": "test-service"}}
      ]
    },
    "scopeSpans": [{
      "scope": {"name": "test-scope"},
      "spans": [{
        "traceId": "$TRACE_ID",
        "spanId": "$SPAN_ID",
        "name": "test-mlflow-ingestion",
        "kind": 1,
        "startTimeUnixNano": "$(date +%s)000000000",
        "endTimeUnixNano": "$(date +%s)500000000",
        "attributes": [
          {"key": "mlflow.traceRequestId", "value": {"stringValue": "$TRACE_ID_SHORT"}},
          {"key": "mlflow.spanType", "value": {"stringValue": "CHAT_MODEL"}},
          {"key": "mlflow.user", "value": {"stringValue": "test-user"}},
          {"key": "mlflow.session", "value": {"stringValue": "test-session-123"}},
          {"key": "mlflow.traceName", "value": {"stringValue": "test-trace-name"}},
          {"key": "mlflow.source.name", "value": {"stringValue": "test-source"}},
          {"key": "mlflow.source.type", "value": {"stringValue": "GENAI"}},
          {"key": "mlflow.promptTokens", "value": {"intValue": "42"}},
          {"key": "mlflow.completionTokens", "value": {"intValue": "84"}},
          {"key": "mlflow.totalTokens", "value": {"intValue": "126"}},
          {"key": "mlflow.spanInputs", "value": {"stringValue": "Test input prompt for verification"}},
          {"key": "mlflow.spanOutputs", "value": {"stringValue": "Test output response for verification"}},
          {"key": "gen_ai.request.model", "value": {"stringValue": "test-model"}},
          {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
          {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "42"}},
          {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "84"}}
        ]
      }]
    }]
  }]
}
EOF

echo -e "${GREEN}✓${NC} Test trace generated with trace ID: $TRACE_ID_SHORT"

echo -e "\n${YELLOW}[2/5]${NC} Sending trace to OTel Collector..."

# Port-forward to OTel Collector
kubectl port-forward -n $NAMESPACE svc/otel-collector 4318:4318 > /dev/null 2>&1 &
PF_PID=$!
sleep 2

# Send trace via OTLP HTTP
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d @/tmp/test-trace.json)

kill $PF_PID 2>/dev/null || true

if [[ "$HTTP_CODE" == "200" ]]; then
  echo -e "${GREEN}✓${NC} Trace sent successfully (HTTP $HTTP_CODE)"
else
  echo -e "${RED}✗${NC} Failed to send trace (HTTP $HTTP_CODE)"
  exit 1
fi

echo -e "\n${YELLOW}[3/5]${NC} Waiting for trace to be ingested by MLflow..."
sleep 5

echo -e "\n${YELLOW}[4/5]${NC} Checking MLflow database tables...\n"

# Check if span was ingested
echo -e "${BLUE}Checking spans table...${NC}"
SPAN_COUNT=$(kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -t -c \
  "SELECT COUNT(*) FROM spans WHERE trace_id LIKE '%$TRACE_ID_SHORT%';" 2>/dev/null | tr -d ' ')

if [[ "$SPAN_COUNT" -gt 0 ]]; then
  echo -e "${GREEN}✓${NC} Span found in spans table"

  # Show span attributes
  echo -e "\n${BLUE}Span content (mlflow.* attributes):${NC}"
  kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -c \
    "SELECT content::json->'attributes' as attributes FROM spans WHERE trace_id LIKE '%$TRACE_ID_SHORT%' LIMIT 1;" 2>/dev/null | head -20
else
  echo -e "${RED}✗${NC} Span NOT found in spans table"
  exit 1
fi

# Check trace_tags table (MLflow UI columns)
echo -e "\n${BLUE}Checking trace_tags table...${NC}"
TAG_COUNT=$(kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -t -c \
  "SELECT COUNT(*) FROM trace_tags WHERE request_id LIKE '%$TRACE_ID_SHORT%';" 2>/dev/null | tr -d ' ')

if [[ "$TAG_COUNT" -gt 0 ]]; then
  echo -e "${GREEN}✓${NC} Found $TAG_COUNT entries in trace_tags"

  echo -e "\n${BLUE}trace_tags entries:${NC}"
  kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -c \
    "SELECT key, value FROM trace_tags WHERE request_id LIKE '%$TRACE_ID_SHORT%' ORDER BY key;" 2>/dev/null
else
  echo -e "${RED}✗${NC} NO entries in trace_tags (MLflow did NOT auto-populate)"
fi

# Check trace_info table (request/response previews)
echo -e "\n${BLUE}Checking trace_info table...${NC}"
INFO_COUNT=$(kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -t -c \
  "SELECT COUNT(*) FROM trace_info WHERE request_id LIKE '%$TRACE_ID_SHORT%';" 2>/dev/null | tr -d ' ')

if [[ "$INFO_COUNT" -gt 0 ]]; then
  echo -e "${GREEN}✓${NC} Found entry in trace_info"

  echo -e "\n${BLUE}trace_info entry:${NC}"
  kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -c \
    "SELECT request_id, request_preview, response_preview FROM trace_info WHERE request_id LIKE '%$TRACE_ID_SHORT%';" 2>/dev/null
else
  echo -e "${RED}✗${NC} NO entry in trace_info (MLflow did NOT create trace_info record)"
fi

# Check trace_request_metadata table
echo -e "\n${BLUE}Checking trace_request_metadata table...${NC}"
METADATA_COUNT=$(kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -t -c \
  "SELECT COUNT(*) FROM trace_request_metadata WHERE request_id LIKE '%$TRACE_ID_SHORT%';" 2>/dev/null | tr -d ' ')

if [[ "$METADATA_COUNT" -gt 0 ]]; then
  echo -e "${GREEN}✓${NC} Found $METADATA_COUNT entries in trace_request_metadata"

  echo -e "\n${BLUE}trace_request_metadata entries:${NC}"
  kubectl exec -n $NAMESPACE $POSTGRES_POD -- psql -U postgres -d mlflow -c \
    "SELECT key, value FROM trace_request_metadata WHERE request_id LIKE '%$TRACE_ID_SHORT%' ORDER BY key;" 2>/dev/null
else
  echo -e "${RED}✗${NC} NO entries in trace_request_metadata"
fi

# Summary
echo -e "\n${BLUE}======================================${NC}"
echo -e "${BLUE}Test Results Summary${NC}"
echo -e "${BLUE}======================================${NC}\n"

echo "Trace ID: $TRACE_ID_SHORT"
echo "Spans table: $SPAN_COUNT records"
echo "trace_tags table: $TAG_COUNT records"
echo "trace_info table: $INFO_COUNT records"
echo "trace_request_metadata table: $METADATA_COUNT records"

echo -e "\n${YELLOW}[5/5]${NC} Analysis:\n"

if [[ "$TAG_COUNT" -eq 0 ]] && [[ "$INFO_COUNT" -eq 0 ]]; then
  echo -e "${RED}RESULT: MLflow does NOT auto-populate trace_tags/trace_info from span attributes${NC}"
  echo -e "${YELLOW}CONCLUSION: Enrichment Service IS REQUIRED to populate MLflow UI columns${NC}"
  echo ""
  echo "The span was ingested with all mlflow.* attributes, but MLflow's OTLP"
  echo "ingestion did not create entries in trace_tags or trace_info tables."
  echo "The enrichment service is needed to extract data from span content and"
  echo "backfill these tables for the MLflow UI to display the data."
elif [[ "$TAG_COUNT" -gt 0 ]] && [[ "$INFO_COUNT" -gt 0 ]]; then
  echo -e "${GREEN}RESULT: MLflow DOES auto-populate trace_tags/trace_info from span attributes${NC}"
  echo -e "${GREEN}CONCLUSION: Enrichment Service can be ELIMINATED - OTel Collector is sufficient${NC}"
  echo ""
  echo "MLflow's OTLP ingestion automatically created entries in trace_tags and"
  echo "trace_info based on the mlflow.* attributes in the span. We can remove"
  echo "the enrichment service and rely solely on the OTel Collector transform"
  echo "processor to add the necessary attributes."
else
  echo -e "${YELLOW}RESULT: Partial auto-population (tags=$TAG_COUNT, info=$INFO_COUNT)${NC}"
  echo -e "${YELLOW}CONCLUSION: Further investigation needed${NC}"
fi

echo ""
