# LlamaStack Custom Image with MLflow Tracing

Custom LlamaStack image for AI Catalyst Lab with:
- OpenTelemetry auto-instrumentation (FastAPI + OpenAI spans)
- **MLflow Python SDK middleware** (populates MLflow UI fields)
- Agents API hotfix (NoneType crash with tool calling)
- vLLM embedding dimensions compatibility fix

## MLflow Middleware

The `mlflow_middleware.py` FastAPI middleware wraps inference requests with MLflow's Python SDK to populate UI fields that OpenTelemetry's OTLP receiver cannot:

| MLflow UI Field | Populated By | Value |
|-----------------|--------------|-------|
| **Request** | mlflow.start_trace(inputs=...) | Request messages, model, params |
| **Response** | trace.set_outputs(...) | Response data, status code, execution time |
| **Session** | trace tags (mlflow.sessionId) | From X-Session-ID header or "llamastack-default" |
| **User** | trace tags (mlflow.userId) | From X-User-ID header or "system" |
| **Trace name** | mlflow.start_trace(name=...) | "chat {model}" or endpoint path |
| **Version** | trace tags (mlflow.version) | Extracted from model name |
| **Tokens** | ✅ Already working via OTel | gen_ai.usage.input_tokens/output_tokens |

**How it works:**
1. Middleware intercepts requests to `/v1/chat/completions`, `/v1/embeddings`, `/v1/agents`
2. Creates MLflow trace with request data as inputs
3. Calls downstream handler (preserves OTel instrumentation)
4. Captures response and sets as trace outputs
5. MLflow writes trace_info table with request_preview/response_preview

**Result:** All MLflow UI columns populated instead of showing `null`.

## Building the Image

### Prerequisites
- `podman` or `docker`
- Access to `quay.io/aicatalyst` registry

### Build Command

```bash
cd llamastack/

# Build with podman (recommended)
podman build -t quay.io/aicatalyst/llamastack-starter:0.5.1-mlflow -f Containerfile .

# Or with docker
docker build -t quay.io/aicatalyst/llamastack-starter:0.5.1-mlflow -f Containerfile .
```

### Push to Registry

```bash
# Podman
podman push quay.io/aicatalyst/llamastack-starter:0.5.1-mlflow

# Docker
docker push quay.io/aicatalyst/llamastack-starter:0.5.1-mlflow
```

## Deploying to Cluster

### Update Deployment

Edit [llamastack.yaml](llamastack.yaml) to use the new image:

```yaml
spec:
  template:
    spec:
      containers:
      - name: llamastack
        image: quay.io/aicatalyst/llamastack-starter:0.5.1-mlflow  # Updated
```

### Apply to Cluster

```bash
# Copy updated deployment
scp llamastack.yaml root@<CLUSTER_IP>:/tmp/

# Apply
ssh root@<CLUSTER_IP> 'kubectl apply -f /tmp/llamastack.yaml'

# Restart to load new image
ssh root@<CLUSTER_IP> 'kubectl rollout restart deployment llamastack -n catalystlab-shared'

# Wait for rollout
ssh root@<CLUSTER_IP> 'kubectl rollout status deployment llamastack -n catalystlab-shared'
```

### Verify MLflow UI

1. Send test request:
   ```bash
   kubectl run curl-test --image=curlimages/curl:latest --rm -i --restart=Never \
     --namespace=catalystlab-shared -- \
     curl -X POST http://llamastack.catalystlab-shared.svc.cluster.local:8321/v1/chat/completions \
     -H "Content-Type: application/json" \
     -H "X-User-ID: test-user" \
     -H "X-Session-ID: test-session-123" \
     -d '{"model": "vllm/RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 10}'  # pragma: allowlist secret
   ```

2. Check MLflow UI (http://mlflow.<CLUSTER_IP>.nip.io):
   - **Request column**: Should show message content, model, parameters
   - **Response column**: Should show response data
   - **Session column**: Should show "test-session-123"
   - **User column**: Should show "test-user"
   - **Trace name column**: Should show "chat vllm/RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8"
   - **Version column**: Should show "Qwen3-Next-80B-A3B-Instruct-FP8"

## Configuration

The middleware reads these environment variables (already set in deployment):

- `MLFLOW_TRACKING_URI`: MLflow server URL (default: cluster service)
- `MLFLOW_EXPERIMENT_NAME`: Experiment name (default: "llamastack-traces")

## Architecture

**Dual Tracing:**
- **OpenTelemetry (auto-instrumentation)**: Captures low-level spans (HTTP requests, OpenAI calls) → sent to OTel Collector → exported to MLflow + Jaeger
- **MLflow SDK (middleware)**: Captures high-level trace metadata (request/response content, session, user) → sent directly to MLflow REST API

**Data Flow:**
```
Request → MLflow Middleware (start trace)
           ↓
       FastAPI handler (OTel auto-instrumented)
           ↓
       vLLM call (OTel captures gen_ai.* attributes)
           ↓
       MLflow Middleware (set outputs, end trace)
           ↓
       ├─→ MLflow SDK → mlflow:5000/api/2.0/mlflow/traces (trace_info, trace_tags)
       └─→ OTel spans → otel-collector:4317 → mlflow:5000/v1/traces (spans table)
```

**Result:** MLflow receives BOTH:
1. High-level trace metadata via Python SDK (populates UI fields)
2. Detailed span data via OTel Collector (gen_ai attributes, timing, etc.)

## Troubleshooting

### Middleware not loading

Check container logs for import errors:
```bash
kubectl logs -n catalystlab-shared -l app=llamastack --tail=50 | grep -i mlflow
```

Expected: No errors. If you see `ModuleNotFoundError: No module named 'mlflow'`, the pip install failed during build.

### UI fields still showing null

1. Verify middleware is active:
   ```bash
   kubectl exec -n catalystlab-shared <llamastack-pod> -- python3 -c "import llama_stack.distribution.mlflow_middleware; print('OK')"
   ```

2. Check MLflow server received trace:
   ```bash
   # Query trace_info table
   ssh root@<CLUSTER_IP> 'kubectl exec -n catalystlab-shared mlflow-<pod> -- python3 -c "
   import psycopg2, os, json
   conn = psycopg2.connect(host=\"pgvector-cluster-rw\", database=\"mlflow\", user=os.environ[\"POSTGRES_USER\"], password=os.environ[\"POSTGRES_PASSWORD\"])
   cur = conn.cursor()
   cur.execute(\"SELECT request_preview, response_preview FROM trace_info ORDER BY timestamp_ms DESC LIMIT 1;\")
   print(cur.fetchone())
   "'
   ```

   Should show request/response data, not `(None, None)`.

### Dual traces appearing

If you see duplicate traces (one from SDK, one from OTel), the middleware and OTel auto-instrumentation are both creating root traces. This is expected and correct:
- **SDK trace** (via middleware) = trace-level metadata with request/response
- **OTel trace** (via auto-instrumentation) = span-level details with gen_ai attributes

MLflow should correlate them via trace_id if both use the same OpenTelemetry context.

## Files

- [Containerfile](Containerfile) - Image build with middleware injection
- [mlflow_middleware.py](mlflow_middleware.py) - FastAPI middleware implementation
- [llamastack.yaml](llamastack.yaml) - Kubernetes deployment manifest
- [llamastack-config.yaml](llamastack-config.yaml) - LlamaStack runtime configuration

## References

- [MLflow Tracing Python API](https://mlflow.org/docs/latest/llms/tracing/index.html)
- [LlamaStack Distribution](https://github.com/meta-llama/llama-stack)
- [OpenTelemetry Python Instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/)
