#!/usr/bin/env bash
# demo-scenario.sh -- Generate traffic through the full AI stack and open observability views
#
# This script demonstrates the end-to-end flow:
#   1. Agent queries via A2A (labdemo-agent health check, architecture Q, log analysis)
#   2. Direct LLM inference via LLaMA Stack OpenAI API
#   3. Quick GuideLLM benchmark burst
#   4. Opens all observability views to show the traffic propagating
#
# Usage:
#   ./scripts/demo-scenario.sh                  # Full demo (requires cluster access)
#   ./scripts/demo-scenario.sh --dry-run        # Print commands without executing
#   ./scripts/demo-scenario.sh --urls-only      # Just print observability URLs
#   ./scripts/demo-scenario.sh --skip-benchmark # Skip the GuideLLM burst
#
# Prerequisites:
#   - kubectl configured with cluster access
#   - Ingress IP set in INGRESS_IP env var (or pass as argument)
#
set -euo pipefail

# --- Configuration ---
INGRESS_IP="${INGRESS_IP:-<INGRESS_IP>}"
GRAFANA_IP="${GRAFANA_IP:-<GRAFANA_LB_IP>}"
LLAMASTACK_SVC="llamastack.catalystlab-shared.svc.cluster.local:8321"
LABDEMO_SVC="labdemo-agent.kagent.svc.cluster.local:8080"
GUIDELLM_NAMESPACE="guide-llm"
MODEL="RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8"

DRY_RUN=false
URLS_ONLY=false
SKIP_BENCHMARK=false

# Parse arguments
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --urls-only) URLS_ONLY=true ;;
    --skip-benchmark) SKIP_BENCHMARK=true ;;
    --help|-h)
      echo "Usage: $0 [--dry-run] [--urls-only] [--skip-benchmark]"
      exit 0
      ;;
    *)
      # Treat as INGRESS_IP if it looks like an IP
      if [[ "$arg" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        INGRESS_IP="$arg"
      fi
      ;;
  esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() { echo -e "\n${BLUE}=== $1 ===${NC}\n"; }
print_ok()     { echo -e "${GREEN}[OK]${NC} $1"; }
print_warn()   { echo -e "${YELLOW}[!!]${NC} $1"; }
print_url()    { echo -e "  ${GREEN}->  $1${NC}"; }

# Helper: run kubectl exec in an ephemeral pod or existing pod
kube_curl() {
  local url=$1
  local data=${2:-}

  if [ "$DRY_RUN" = true ]; then
    if [ -n "$data" ]; then
      echo "  kubectl run curl-demo --rm -i --restart=Never --image=curlimages/curl -- -s -X POST '$url' -H 'Content-Type: application/json' -d '$data'"
    else
      echo "  kubectl run curl-demo --rm -i --restart=Never --image=curlimages/curl -- -s '$url'"
    fi
    return
  fi

  if [ -n "$data" ]; then
    kubectl run "curl-demo-$$" --rm -i --restart=Never \
      --image=curlimages/curl \
      --namespace=catalystlab-shared \
      -- -s -m 30 -X POST "$url" \
         -H 'Content-Type: application/json' \
         -d "$data" 2>/dev/null || echo "(request timed out or failed)"
  else
    kubectl run "curl-demo-$$" --rm -i --restart=Never \
      --image=curlimages/curl \
      --namespace=catalystlab-shared \
      -- -s -m 10 "$url" 2>/dev/null || echo "(request timed out or failed)"
  fi
}

# A2A JSON-RPC helper (A2A v0.3.0 protocol: method=message/send, messageId required)
a2a_query() {
  local agent_url=$1
  local message=$2
  local msg_id
  msg_id="demo-$(date +%s)-$RANDOM"

  local payload
  payload=$(cat <<EOF
{
  "jsonrpc": "2.0",
  "id": "${msg_id}",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "messageId": "${msg_id}",
      "parts": [{"text": "${message}"}]
    }
  }
}
EOF
  )
  kube_curl "http://${agent_url}/" "$payload"
}

# --- Observability URLs ---
print_urls() {
  print_header "Observability Views"

  echo "Open these in your browser to watch traffic propagate:"
  echo ""
  echo "Grafana (Dashboard + Node Graph):"
  print_url "http://${GRAFANA_IP}/d/catalyst-lab-overview"
  echo ""
  echo "Jaeger (Trace Trees + Dependency Graph):"
  print_url "http://jaeger.${INGRESS_IP}.nip.io/search?service=kagent"
  print_url "http://jaeger.${INGRESS_IP}.nip.io/dependencies"
  echo ""
  echo "Kiali (Istio Mesh Topology -- animated edges):"
  print_url "http://kiali.${INGRESS_IP}.nip.io/kiali/console/graph/namespaces/?namespaces=catalystlab-shared,kagent,kserve-lab"
  echo ""
  echo "MLflow (Experiment Tracking + Traces):"
  print_url "http://mlflow.${INGRESS_IP}.nip.io/#/experiments/1/traces"
  echo ""
  echo "Kagent UI (Agent Interaction):"
  print_url "http://kagent.${INGRESS_IP}.nip.io"
  echo ""

  if [ "$INGRESS_IP" = "<INGRESS_IP>" ]; then
    print_warn "Set INGRESS_IP env var or pass IP as argument for real URLs"
  fi
}

if [ "$URLS_ONLY" = true ]; then
  print_urls
  exit 0
fi

# --- Pre-flight checks ---
print_header "Pre-flight Checks"

if [ "$DRY_RUN" = false ]; then
  # Check LLaMA Stack is reachable
  echo -n "LLaMA Stack... "
  if kubectl exec -n catalystlab-shared deploy/llamastack -- curl -s -o /dev/null -w "%{http_code}" http://localhost:8321/v1/models 2>/dev/null | grep -q 200; then
    print_ok "reachable"
  else
    print_warn "LLaMA Stack not reachable -- some demo steps may fail"
  fi

  # Check labdemo-agent is Ready
  echo -n "labdemo-agent... "
  if kubectl get agent labdemo-agent -n kagent -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null | grep -q True; then
    print_ok "Ready"
  else
    print_warn "labdemo-agent not Ready -- A2A queries may fail"
  fi
else
  echo "(dry-run: skipping pre-flight checks)"
fi

# --- Step 1: Agent Queries via A2A ---
print_header "Step 1: Agent Queries via A2A (labdemo-agent)"

echo "Query 1: Health check"
a2a_query "$LABDEMO_SVC" "Is the lab healthy? Give me a quick status of all namespaces."
echo ""

echo "Query 2: Architecture question"
a2a_query "$LABDEMO_SVC" "How does the observability pipeline work? Describe the trace fan-out."
echo ""

echo "Query 3: Log analysis"
a2a_query "$LABDEMO_SVC" "Check the OTel collector logs for any errors in the last 5 minutes."
echo ""

# --- Step 2: Direct LLM Inference ---
print_header "Step 2: Direct LLM Inference via LLaMA Stack"

echo "Sending a chat completion request..."
kube_curl "http://${LLAMASTACK_SVC}/v1/chat/completions" \
  "{\"model\": \"${MODEL}\", \"messages\": [{\"role\": \"user\", \"content\": \"What are the key components of a Kubernetes-native AI observability stack? Answer in 3 bullet points.\"}], \"max_tokens\": 256}"
echo ""

# --- Step 3: GuideLLM Benchmark Burst ---
if [ "$SKIP_BENCHMARK" = false ]; then
  print_header "Step 3: Quick GuideLLM Burst (10 requests)"

  local_job_name="guidellm-demo-burst"

  if [ "$DRY_RUN" = true ]; then
    echo "  Would run: kubectl apply -f (inline Job: 10 requests, 2 req/s, constant profile)"
    echo "  Would wait for completion, then show logs"
  else
    # Delete previous burst if exists
    kubectl delete job "${local_job_name}" -n "${GUIDELLM_NAMESPACE}" --ignore-not-found=true 2>/dev/null

    cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ${local_job_name}
  namespace: ${GUIDELLM_NAMESPACE}
  labels:
    app: guidellm-demo
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: guidellm
          image: ghcr.io/vllm-project/guidellm:latest
          args:
            - "benchmark"
            - "run"
            - "--target"
            - "http://${LLAMASTACK_SVC}"
            - "--model"
            - "${MODEL}"
            - "--data"
            - '{"prompt_tokens": 64, "output_tokens": 32}'
            - "--rate"
            - "2"
            - "--profile"
            - "constant"
            - "--max-number"
            - "10"
            - "--processor"
            - "${MODEL}"
            - "--backend-kwargs"
            - '{"validate_backend": false}'
          resources:
            requests:
              cpu: "1"
              memory: 1Gi
            limits:
              cpu: "2"
              memory: 2Gi
EOF
    echo "Waiting for burst to complete (up to 120s)..."
    if kubectl wait --for=condition=complete "job/${local_job_name}" -n "${GUIDELLM_NAMESPACE}" --timeout=120s 2>/dev/null; then
      print_ok "Burst complete"
      kubectl logs "job/${local_job_name}" -n "${GUIDELLM_NAMESPACE}" --tail=5
    else
      print_warn "Burst did not complete within 120s"
      kubectl logs "job/${local_job_name}" -n "${GUIDELLM_NAMESPACE}" --tail=10
    fi
  fi
else
  print_header "Step 3: GuideLLM Burst (skipped)"
fi

# --- Step 4: Show Observability URLs ---
print_urls

print_header "Demo Complete"
echo "Traffic has been generated through:"
echo "  - Agent layer (3 A2A queries -> labdemo-agent -> LLaMA Stack -> vLLM)"
echo "  - Direct inference (1 chat completion -> LLaMA Stack -> vLLM)"
if [ "$SKIP_BENCHMARK" = false ]; then
  echo "  - Benchmark burst (10 requests -> LLaMA Stack -> vLLM)"
fi
echo ""
echo "All traces should now be visible in the observability views above."
echo "The Grafana node graph and Kiali mesh should show animated edges."
echo "Jaeger should show trace trees with 90-200+ spans per agent query."
