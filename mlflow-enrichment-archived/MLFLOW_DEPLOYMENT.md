# MLflow Tracing Middleware for LlamaStack

This directory contains two approaches for adding MLflow tracing to LlamaStack deployments. Both populate MLflow UI fields (Session, User, Version, Trace Name, Request, Response) that OpenTelemetry auto-instrumentation alone cannot fill.

## Approach 1: ConfigMap Injection (Recommended)

**Pros:**
- No custom image to maintain
- All code lives in Kubernetes manifests (version controlled)
- Easy to update middleware (just edit ConfigMap and restart pods)
- Works with any upstream llamastack image

**Cons:**
- Patches Python files at runtime (could break if upstream changes)
- Slightly longer startup time (~2-3 seconds)

### Deployment Steps

```bash
# 1. Apply the MLflow middleware ConfigMap
kubectl apply -f mlflow-configmap.yaml

# 2. Patch the llamastack deployment to inject the middleware
kubectl patch deployment llamastack -n catalystlab-shared --patch-file deployment-mlflow-patch.yaml

# 3. Wait for rollout to complete
kubectl rollout status deployment llamastack -n catalystlab-shared

# 4. Verify middleware is loaded
kubectl logs -n catalystlab-shared deployment/llamastack -c llamastack | grep "MLflow Injector"
```

### How It Works

1. **ConfigMap** contains:
   - `mlflow_middleware.py`: The FastAPI middleware that creates MLflow traces
   - `inject-middleware.sh`: Startup script that patches the middleware into site-packages

2. **Deployment changes**:
   - Mounts the ConfigMap at `/mlflow-config`
   - Overrides the container command to run `inject-middleware.sh`
   - The script copies the middleware file and patches `server.py` to import it
   - Then execs the original `llama stack run` command

3. **Runtime behavior**:
   - Intercepts requests to `/v1/chat/completions`, `/v1/embeddings`, `/v1/agents`
   - Creates MLflow trace with span using `mlflow.start_span()`
   - Captures request inputs and response outputs
   - Schedules background task to update trace metadata (User, Session, Version, Trace Name)
   - Background task waits 1 second for async trace writing to complete before adding metadata

### Updating the Middleware

```bash
# Edit the ConfigMap
kubectl edit configmap llamastack-mlflow-middleware -n catalystlab-shared

# Restart pods to pick up changes
kubectl rollout restart deployment llamastack -n catalystlab-shared
```

## Approach 2: Custom Container Image

**Pros:**
- Middleware is baked into the image (no runtime patching)
- Faster startup time
- More predictable behavior

**Cons:**
- Requires maintaining a custom image
- Need to rebuild for upstream updates or middleware changes
- More complex CI/CD pipeline

### Build and Deploy

```bash
# Build the image
cd llamastack
podman build --platform linux/amd64 -t quay.io/aicatalyst/llamastack-starter:0.5.1-mlflow -f Containerfile .

# Push to registry (requires write access to quay.io/aicatalyst)
podman push quay.io/aicatalyst/llamastack-starter:0.5.1-mlflow

# OR import directly to cluster (for testing)
podman save quay.io/aicatalyst/llamastack-starter:0.5.1-mlflow | \
  ssh root@<CLUSTER_IP> 'cat > /tmp/llamastack-mlflow.tar'
ssh root@<CLUSTER_IP> 'ctr -n k8s.io images import /tmp/llamastack-mlflow.tar'

# Update deployment
kubectl set image deployment/llamastack llamastack=quay.io/aicatalyst/llamastack-starter:0.5.1-mlflow \
  -n catalystlab-shared
```

### Containerfile Explanation

The [Containerfile](Containerfile) performs these steps:

1. Starts from upstream `llamastack/distribution-starter` image
2. Installs MLflow SDK and OpenTelemetry instrumentation libraries
3. Applies hotfixes for known upstream bugs (None type joining, embedding dimensions)
4. Copies `mlflow_middleware.py` into site-packages
5. Patches `server.py` to import and register the middleware
6. Verifies patches were applied successfully

## Usage

Once deployed (via either approach), send requests with custom headers:

```bash
curl -X POST http://llamastack.<CLUSTER_IP>.nip.io/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-ID: alice" \
  -H "X-Session-ID: session-123" \
  -d '{
    "model": "vllm/RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8",  # pragma: allowlist secret
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 50
  }'
```

The trace will appear in MLflow UI at `http://mlflow.<CLUSTER_IP>.nip.io` with:
- **User**: `alice` (from `X-User-ID` header, defaults to `system`)
- **Session**: `session-123` (from `X-Session-ID` header, defaults to `llamastack-default`)
- **Version**: `Qwen3-Next-80B-A3B-Instruct-FP8` (extracted from model name)
- **Trace Name**: `chat vllm/RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8`
- **Request**: Full JSON request body
- **Response**: Full JSON response body

## Architecture

```
┌─────────────────┐
│   Client        │
│  (curl/SDK)     │
└────────┬────────┘
         │ HTTP Request
         │ Headers: X-User-ID, X-Session-ID
         ▼
┌─────────────────────────────────────────┐
│  LlamaStack Pod                         │
│  ┌───────────────────────────────────┐  │
│  │  MLflow Middleware                │  │
│  │  - Intercepts request             │  │
│  │  - Creates MLflow span            │  │
│  │  - Captures inputs/outputs        │  │
│  │  - Schedules background task      │  │
│  └───────────┬───────────────────────┘  │
│              │                           │
│              ▼                           │
│  ┌───────────────────────────────────┐  │
│  │  LlamaStack Server                │  │
│  │  - Processes request              │  │
│  │  - Calls vLLM backend             │  │
│  └───────────┬───────────────────────┘  │
│              │                           │
│              │ (OTel traces also sent)  │
└──────────────┼───────────────────────────┘
               │
        ┌──────┴──────┬─────────────┐
        │             │             │
        ▼             ▼             ▼
  ┌─────────┐   ┌─────────┐  ┌─────────┐
  │ MLflow  │   │ Jaeger  │  │  Tempo  │
  │ (traces)│   │ (spans) │  │ (spans) │
  └─────────┘   └─────────┘  └─────────┘
        │
        │ Background task
        │ (after 1s delay)
        ▼
  ┌──────────────────────────┐
  │  PostgreSQL              │
  │  - trace_info            │
  │  - trace_request_metadata│
  │  - trace_tags            │
  │  - spans                 │
  └──────────────────────────┘
```

## Troubleshooting

### MLflow UI columns still empty

**Check 1: Verify middleware is loaded**
```bash
kubectl exec -n catalystlab-shared deployment/llamastack -c llamastack -- \
  ls -la /usr/local/lib/python3.12/site-packages/llama_stack/core/server/mlflow_middleware.py
```

**Check 2: Verify background task logs**
```bash
kubectl logs -n catalystlab-shared deployment/llamastack -c llamastack | grep "\[MLflow\]"
```

Expected output:
```
INFO ... [MLflow] Starting background metadata update for trace tr-abc123...
INFO ... [MLflow] Setting metadata for trace tr-abc123: user=alice, session=session-123
INFO ... [MLflow] Successfully updated metadata for trace tr-abc123
```

**Check 3: Query database directly**
```bash
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U postgres -d mlflow -c \
  "SELECT t.request_id, m.key, m.value
   FROM trace_info t
   LEFT JOIN trace_request_metadata m ON t.request_id = m.request_id
   WHERE m.key IN ('mlflow.trace.user', 'mlflow.trace.session')
   ORDER BY t.timestamp_ms DESC LIMIT 5;"
```

### Foreign key constraint violations

This happens when the background task tries to add metadata before the trace is written to the database.

**Solution**: The middleware already waits 1 second. If you still see this error, increase the sleep duration in `update_trace_metadata_background()`:

```python
time.sleep(2.0)  # Increase from 1.0 to 2.0
```

### Middleware not intercepting requests

**Check 1: Verify endpoint matches**
The middleware only intercepts:
- `/v1/chat/completions`
- `/v1/embeddings`
- `/v1/agents`

Other endpoints (like `/v1/models`) are skipped.

**Check 2: Verify middleware registration**
```bash
kubectl exec -n catalystlab-shared deployment/llamastack -c llamastack -- \
  grep -A2 "add_middleware(MLflowTracingMiddleware)" \
  /usr/local/lib/python3.12/site-packages/llama_stack/core/server/server.py
```

## Migration from Custom Image to ConfigMap

If currently using the custom image approach:

```bash
# 1. Apply ConfigMap
kubectl apply -f mlflow-configmap.yaml

# 2. Patch deployment to use upstream image + ConfigMap
kubectl patch deployment llamastack -n catalystlab-shared --patch-file deployment-mlflow-patch.yaml

# 3. The rollout will happen automatically
kubectl rollout status deployment llamastack -n catalystlab-shared
```

## Security Considerations

⚠️ **WARNING**: This deployment has no authentication and is suitable ONLY for lab environments.

**Current security gaps:**
- MLflow UI has no authentication
- Trace data contains full request/response bodies (may include sensitive data)
- No encryption in transit (HTTP, not HTTPS)

**For production:**
- Enable MLflow authentication (OAuth2 or basic auth)
- Implement TLS/HTTPS for all services
- Add RBAC policies to restrict access
- Consider redacting sensitive fields from traces
- Enable audit logging

## References

- [MLflow Tracing Documentation](https://mlflow.org/docs/latest/llms/tracing/index.html)
- [OpenTelemetry Python Instrumentation](https://opentelemetry.io/docs/languages/python/automatic/)
- [LlamaStack GitHub](https://github.com/meta-llama/llama-stack)
