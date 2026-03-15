#!/usr/bin/env bash
# run-benchmark-sweep.sh -- Run GuideLLM benchmarks at multiple concurrency levels
#
# Runs the benchmark Job at each specified concurrency level, waits for completion,
# and optionally uploads results to MLflow.
#
# Usage:
#   ./scripts/run-benchmark-sweep.sh
#   ./scripts/run-benchmark-sweep.sh --upload-to-mlflow
#   ./scripts/run-benchmark-sweep.sh --dry-run
#
# Prerequisites:
#   - kubectl configured with cluster access
#   - benchmark-results-pvc exists in guide-llm namespace
#   - LLaMA Stack accessible at the configured endpoint
#
set -euo pipefail

# --- Configuration ---
NAMESPACE="guide-llm"
ENDPOINT="http://llamastack.catalystlab-shared.svc.cluster.local:8321"
MODEL="RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8"
HF_MODEL_ID="RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8"
CONCURRENCY_LEVELS=(1 2 4 8)
DURATION=60
DATA='{"prompt_tokens": 128, "output_tokens": 64}'
DRY_RUN=false
UPLOAD=false

# Parse arguments
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --upload-to-mlflow) UPLOAD=true ;;
    --help|-h)
      echo "Usage: $0 [--dry-run] [--upload-to-mlflow]"
      echo ""
      echo "Runs GuideLLM benchmarks at concurrency levels: ${CONCURRENCY_LEVELS[*]}"
      echo "Each run lasts ${DURATION} seconds."
      echo ""
      echo "Options:"
      echo "  --dry-run           Print Job manifests without applying"
      echo "  --upload-to-mlflow  Upload results to MLflow after each run"
      exit 0
      ;;
  esac
done

run_benchmark() {
  local concurrency=$1
  local job_name="guidellm-benchmark-c${concurrency}"

  echo "=== Benchmark: concurrency=${concurrency}, duration=${DURATION}s ==="

  # Generate the Job manifest
  local manifest
  manifest=$(cat <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${job_name}
  namespace: ${NAMESPACE}
  labels:
    app: guidellm-benchmark
    concurrency: "${concurrency}"
spec:
  backoffLimit: 0
  template:
    metadata:
      labels:
        app: guidellm-benchmark
        concurrency: "${concurrency}"
    spec:
      restartPolicy: Never
      containers:
        - name: guidellm
          image: ghcr.io/vllm-project/guidellm:latest
          args:
            - "benchmark"
            - "run"
            - "--target"
            - "${ENDPOINT}"
            - "--model"
            - "${MODEL}"
            - "--data"
            - '${DATA}'
            - "--rate"
            - "${concurrency}"
            - "--profile"
            - "constant"
            - "--max-seconds"
            - "${DURATION}"
            - "--output-dir"
            - "/results/${job_name}"
            - "--outputs"
            - "json,csv"
            - "--processor"
            - "${HF_MODEL_ID}"
            - "--backend-kwargs"
            - '{"validate_backend": false}'
          volumeMounts:
            - name: results
              mountPath: /results
          resources:
            requests:
              cpu: "2"
              memory: 2Gi
            limits:
              cpu: "4"
              memory: 4Gi
      volumes:
        - name: results
          persistentVolumeClaim:
            claimName: benchmark-results-pvc
EOF
  )

  if [ "$DRY_RUN" = true ]; then
    echo "$manifest"
    echo "---"
    return
  fi

  # Delete previous run if exists
  kubectl delete job "${job_name}" -n "${NAMESPACE}" --ignore-not-found=true 2>/dev/null

  # Apply the Job
  echo "$manifest" | kubectl apply -f -

  # Wait for completion (timeout = duration + 120s buffer)
  local timeout=$((DURATION + 120))
  echo "Waiting up to ${timeout}s for ${job_name} to complete..."
  if kubectl wait --for=condition=complete "job/${job_name}" -n "${NAMESPACE}" --timeout="${timeout}s" 2>/dev/null; then
    echo "Benchmark ${job_name} completed successfully."

    # Show brief log summary
    kubectl logs "job/${job_name}" -n "${NAMESPACE}" --tail=10

    if [ "$UPLOAD" = true ]; then
      echo "Uploading results to MLflow..."
      # Copy results from PVC to local temp dir, then upload
      local tmpdir
      tmpdir=$(mktemp -d)
      kubectl cp "${NAMESPACE}/$(kubectl get pods -n "${NAMESPACE}" -l "job-name=${job_name}" -o jsonpath='{.items[0].metadata.name}'):/results/${job_name}" "${tmpdir}/" 2>/dev/null || true
      if ls "${tmpdir}"/*.json 1>/dev/null 2>&1; then
        uv run scripts/guidellm_to_mlflow.py "${tmpdir}" \
          --experiment-name "guidellm-concurrency-sweep" \
          --run-name "${job_name}"
      else
        echo "Warning: No JSON results found to upload."
      fi
      rm -rf "${tmpdir}"
    fi
  else
    echo "WARNING: ${job_name} did not complete within ${timeout}s."
    kubectl logs "job/${job_name}" -n "${NAMESPACE}" --tail=20
  fi

  echo ""
}

# --- Main ---
echo "GuideLLM Concurrency Sweep"
echo "Endpoint: ${ENDPOINT}"
echo "Model: ${MODEL}"
echo "Concurrency levels: ${CONCURRENCY_LEVELS[*]}"
echo "Duration per level: ${DURATION}s"
echo ""

for c in "${CONCURRENCY_LEVELS[@]}"; do
  run_benchmark "$c"
done

echo "=== Sweep complete ==="
if [ "$DRY_RUN" = false ]; then
  echo "Results stored on PVC 'benchmark-results-pvc' in namespace '${NAMESPACE}'."
  echo "To upload to MLflow: $0 --upload-to-mlflow"
fi
