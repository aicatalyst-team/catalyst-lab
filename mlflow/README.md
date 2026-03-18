# MLflow Deployment on Kubernetes

> 📝 **CONFIGURATION NOTE**: This README uses placeholders for environment-specific values. Before deployment, update `ingress.yaml` with your cluster's external IP. Replace `<CLUSTER_IP>` in examples with your nginx ingress external IP.

> 🔄 **ARCHITECTURE NOTE**: The MLflow middleware and enrichment service approach was abandoned on March 17, 2026. Traces now flow directly from LlamaStack (via `opentelemetry-instrument` auto-instrumentation) → OTel Collector → MLflow `/v1/traces` OTLP endpoint. GenAI semantic conventions are captured by OpenTelemetry instrumentation libraries, not custom middleware.

Deploy MLflow as an LLM trace viewer and experiment tracking system in the `catalystlab-shared` namespace. This deployment uses CNPG PostgreSQL for metadata storage and integrates with OpenTelemetry for distributed trace collection from LLaMA Stack inference pipelines.

**Target cluster:** `<CLUSTER_IP>`
**Namespace:** `catalystlab-shared`

## Prerequisites

Before deploying MLflow, verify that the following components are available on your Kubernetes cluster.

### Verification Commands

Run these commands against your cluster to verify prerequisites:

```bash
# Check CNPG PostgreSQL cluster
kubectl get clusters.postgresql.cnpg.io -n catalystlab-shared

# Check pgvector-cluster pods
kubectl get pods -n catalystlab-shared -l cnpg.io/cluster=pgvector-cluster

# Verify PostgreSQL secret exists
kubectl get secret -n catalystlab-shared pgvector-cluster-app

# Check Nginx Ingress Controller
kubectl get ingressclass
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx

# Check storage classes
kubectl get storageclass

# Verify LLaMA Stack deployment
kubectl get deployments -n catalystlab-shared
kubectl get pods -n catalystlab-shared
```

### Expected Results

#### 1. CNPG PostgreSQL Cluster

**Status:**
```
NAME               AGE   INSTANCES   READY   STATUS                     PRIMARY
pgvector-cluster   12h   1           1       Cluster in healthy state   pgvector-cluster-1
```

**Pod:**
```
NAME                 READY   STATUS    RESTARTS   AGE
pgvector-cluster-1   1/1     Running   0          12h
```

**Service endpoints:**
- `pgvector-cluster-rw` (read-write): Primary endpoint for MLflow
- `pgvector-cluster-ro` (read-only): Available for read operations
- `pgvector-cluster-r` (read): Available for read operations

**Existing databases:**
```bash
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- psql -U postgres -c '\l'
```

Expected databases:
- `llamastack` (owner: vectordb)
- `vectordb` (owner: vectordb)
- **Note**: `mlflow` database must be created before deployment

#### 2. PostgreSQL Secret

**Secret name:** `pgvector-cluster-app`

Required keys:
- `username` ✅
- `password` ✅

Verify keys exist:
```bash
kubectl get secret -n catalystlab-shared pgvector-cluster-app \
  -o jsonpath='{.data}' | jq 'keys'
```

Expected output includes `username` and `password` among other connection details.

#### 3. Nginx Ingress Controller

**IngressClass:**
```
NAME    CONTROLLER             PARAMETERS   AGE
nginx   k8s.io/ingress-nginx   <none>       34d
```

**Controller pod:**
```
NAME                                       READY   STATUS    RESTARTS   AGE
ingress-nginx-controller-78c9c55db-zhbtr   1/1     Running   0          24d
```

**Service with external IP:**
```
NAME                       TYPE           EXTERNAL-IP      PORT(S)
ingress-nginx-controller   LoadBalancer   <CLUSTER_IP>   80:31123/TCP,443:31755/TCP
```

**External IP:** `<CLUSTER_IP>` - Used for constructing the MLflow ingress hostname.

#### 4. Storage Provisioner

**Available storage classes:**
```
NAME                   PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE
local-path (default)   rancher.io/local-path   Delete          WaitForFirstConsumer
openebs-hostpath       openebs.io/local        Delete          WaitForFirstConsumer
openebs-lvmpv          local.csi.openebs.io    Delete          Immediate
```

MLflow will use the `local-path` storage class for artifact storage.

**Existing PVCs in catalystlab-shared:**
```
NAME                 STATUS   VOLUME       CAPACITY   STORAGECLASS
llamastack-pvc       Bound    pvc-bdfd...  10Gi       local-path
pgvector-cluster-1   Bound    pvc-cf32...  20Gi       local-path
```

#### 5. LLaMA Stack Deployment

**Deployment:**
```
NAME         READY   UP-TO-DATE   AVAILABLE   AGE
llamastack   1/1     1            1           11h
```

**Pod:**
```
NAME                         READY   STATUS    RESTARTS   AGE
llamastack-9ffb4584c-scswr   1/1     Running   0          11h
```

**Service:**
```
NAME         TYPE        CLUSTER-IP      PORT(S)
llamastack   ClusterIP   10.x.x.x        8321/TCP
```

LLaMA Stack will send OpenTelemetry traces to the OTel Collector, which forwards them to MLflow's `/v1/traces` endpoint.

#### 6. OpenTelemetry Collector

**Status:** Not deployed yet (will be deployed after MLflow)

## Prerequisites Summary

| Component | Status | Details |
|-----------|--------|---------|
| CNPG PostgreSQL Cluster | ✅ Ready | `pgvector-cluster` healthy with 1/1 instances |
| PostgreSQL Secret | ✅ Ready | `pgvector-cluster-app` contains credentials |
| Nginx Ingress | ✅ Ready | External IP: `<CLUSTER_IP>` |
| Storage Provisioner | ✅ Ready | `local-path` storage class available |
| LLaMA Stack | ✅ Ready | Deployment running with service on port 8321 |
| OTel Collector | ⚪ Pending | To be deployed after MLflow |

## Pre-Deployment Action

Before deploying MLflow, create the `mlflow` database in PostgreSQL:

```bash
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U postgres -c "CREATE DATABASE mlflow OWNER vectordb;"
```

Verify the database was created:

```bash
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U postgres -c '\l' | grep mlflow
```

## Deployment

### Step 1: Deploy PVC for Artifacts

```bash
kubectl apply -f pvc.yaml
```

Verify the PVC was created:

```bash
kubectl get pvc -n catalystlab-shared mlflow-artifacts-pvc
```

Expected status: `Pending` (will bind when pod is created)

### Step 2: Deploy MLflow Deployment

```bash
kubectl apply -f deployment.yaml
```

Monitor the deployment:

```bash
kubectl get pods -n catalystlab-shared -l app=mlflow -w
```

Wait for the pod to reach `Running` status.

Check logs for any errors:

```bash
kubectl logs -n catalystlab-shared -l app=mlflow --tail=50
```

### Step 3: Deploy MLflow Service

```bash
kubectl apply -f service.yaml
```

Verify the service:

```bash
kubectl get svc -n catalystlab-shared mlflow
```

Expected output:
```
NAME     TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)    AGE
mlflow   ClusterIP   10.x.x.x       <none>        5000/TCP   ...
```

### Step 4: Deploy MLflow Ingress

```bash
kubectl apply -f ingress.yaml
```

Verify the ingress:

```bash
kubectl get ingress -n catalystlab-shared mlflow
```

Expected output should show the hostname `mlflow.<CLUSTER_IP>.nip.io`.

## Verification

### 1. Health Check (Basic)

**Note:** The `/health` endpoint passes even with broken `--allowed-hosts`, so don't rely on this alone.

```bash
curl http://mlflow.<CLUSTER_IP>.nip.io/health
```

Expected: `OK`

### 2. API Access Test (Real Verification)

This is the **real test** — it will return 403 if `--allowed-hosts` is configured incorrectly:

```bash
curl -X POST http://mlflow.<CLUSTER_IP>.nip.io/api/2.0/mlflow/experiments/search \
  -H 'Content-Type: application/json' -d '{}'
```

Expected: JSON response with empty experiments list (NOT 403)

```json
{"experiments": []}
```

If you get `403 Forbidden` with "DNS rebinding" error, check the `--allowed-hosts` configuration in [deployment.yaml](deployment.yaml).

### 3. Access MLflow UI

Open in browser:

```
http://mlflow.<CLUSTER_IP>.nip.io
```

You should see the MLflow UI with no experiments yet.

## Post-Deployment: OTel Trace Collection

After MLflow is running and verified, set up trace collection:

### 1. Create Initial Experiment

Create an experiment for LLaMA Stack traces:

```bash
curl -X POST http://mlflow.<CLUSTER_IP>.nip.io/api/2.0/mlflow/experiments/create \
  -H 'Content-Type: application/json' \
  -d '{"name": "llamastack-traces"}'
```

**Capture the experiment ID from the response:**

```json
{"experiment_id": "1"}
```

### 2. Deploy OTel Collector

The canonical OTel collector config is in [`../otel-collector/otel-collector.yaml`](../otel-collector/otel-collector.yaml), not the simplified copy in this directory.

```bash
kubectl apply -f ../otel-collector/otel-collector.yaml
```

The canonical config includes probe filtering, MLflow spanType injection, and fan-out to MLflow + Tempo. See [`../otel-collector/README.md`](../otel-collector/README.md) for details.

Verify the OTel Collector is running:

```bash
kubectl get pods -n catalystlab-shared -l app=otel-collector
```

Check logs:

```bash
kubectl logs -n catalystlab-shared -l app=otel-collector --tail=50
```

### 4. Verify LLaMA Stack OTel Configuration

Check that LLaMA Stack is configured to send traces to the OTel Collector:

```bash
kubectl get deployment llamastack -n catalystlab-shared -o yaml | grep OTEL
```

Expected environment variable:
```yaml
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.catalystlab-shared.svc.cluster.local:4317
```

If not configured, update the LLaMA Stack deployment to include this environment variable.

### 5. Verify Traces are Landing

Trigger some inference requests through LLaMA Stack, then check the MLflow UI:

1. Go to: `http://mlflow.<CLUSTER_IP>.nip.io`
2. Click on **Experiments** → **llamastack-traces**
3. Click on the **Traces** tab
4. You should see traces appearing with span details

## Deployment Verification

Use these commands to verify your deployment:

```bash
# Check MLflow components
kubectl get pods,svc,pvc,ingress -n catalystlab-shared -l app=mlflow

# Check OTel Collector
kubectl get pods,svc -n catalystlab-shared -l app=otel-collector

# Verify database
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U postgres -c '\l' | grep mlflow

# Expected resources:
# - Database: mlflow (PostgreSQL)
# - PVC: mlflow-artifacts-pvc (Bound, 10Gi)
# - Deployment: mlflow (1/1 Running)
# - Service: mlflow (ClusterIP, port 5000)
# - Ingress: mlflow (hosts: mlflow.<CLUSTER_IP>.nip.io)
# - OTel Collector: otel-collector (1/1 Running, ports 4317,4318)
```

### Access Information

- **MLflow UI:** `http://mlflow.<CLUSTER_IP>.nip.io` (replace `<CLUSTER_IP>` with your nginx ingress external IP)
- **MLflow API:** `http://mlflow.<CLUSTER_IP>.nip.io/api/2.0/mlflow/`
- **OTel Collector (internal):** `http://otel-collector.catalystlab-shared.svc.cluster.local:4317`

## Trace Data Reference

This section documents what trace data is captured from vLLM (KServe) and other services, what attributes are available, and how to query the data directly.

### Current Trace Coverage

**Total spans in MLflow:** 169,030+ spans across all services (as of March 2026)

**vLLM-related spans:** 5,786 spans (3.4% of total)
- **CHAT_MODEL spans:** 3,829 (high-level LLM inference operations)
- **HTTP POST spans:** 1,395 (low-level HTTP request tracking)

### What's Being Captured from vLLM

#### 1. CHAT_MODEL Spans (GenAI Semantic Conventions)

Client-side instrumentation from llamastack captures comprehensive LLM operation metadata:

**Request attributes:**
```json
{
  "gen_ai.operation.name": "chat",
  "gen_ai.system": "openai",
  "gen_ai.request.model": "RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8",
  "gen_ai.request.temperature": "0.0",
  "gen_ai.request.max_tokens": "256",
  "gen_ai.request.seed": "1234",
  "gen_ai.request.stop_sequences": ["Q:", "</s>", "<|im_end|>"],
  "server.address": "qwen3-next-80b-kserve-workload-svc.kserve-lab.svc.cluster.local",
  "server.port": "8000"
}
```

**Response attributes:**
```json
{
  "gen_ai.response.model": "RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8",
  "gen_ai.response.finish_reasons": ["stop"],
  "gen_ai.response.id": "chatcmpl-78179c79-bc3e-4770-8711-61008dcd1542",
  "gen_ai.usage.input_tokens": "63",
  "gen_ai.usage.output_tokens": "153",
  "mlflow.chat.tokenUsage": {
    "input_tokens": 63,
    "output_tokens": 153,
    "total_tokens": 216
  }
}
```

**Service relationship:**
```json
{
  "peer.service": "vllm"
}
```

**Performance metrics:**
- Span duration: 1.35s - 2.6s (end-to-end inference time)
- Token usage: 57-94 input tokens, 153-256 output tokens per request

#### 2. HTTP POST Spans

Low-level HTTP request tracking via httpx instrumentation:

```json
{
  "http.method": "POST",
  "http.url": "http://qwen3-next-80b-kserve-workload-svc.kserve-lab.svc.cluster.local:8000/v1/chat/completions",
  "http.status_code": "200",
  "peer.service": "vllm"
}
```

**Performance:**
- HTTP overhead: 13ms - 369ms (network + protocol, not inference time)


### Complete Span Examples

These are actual span objects from the MLflow database showing the full structure stored in the `content` column.

#### Example 1: CHAT_MODEL Span (GenAI Inference)

```json
{
  "trace_id": "uSDDdUfXlTq84vG5Kyj1dA==",
  "span_id": "As1A+i6CJK4=",
  "parent_span_id": "PYrGYPZAoK0=",
  "name": "chat RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8",
  "start_time_unix_nano": 1772710823888277097,
  "end_time_unix_nano": 1772710825241951171,
  "events": [],
  "status": {
    "code": "STATUS_CODE_UNSET",
    "message": ""
  },
  "attributes": {
    "mlflow.traceRequestId": "tr-b920c37547d7953abce2f1b92b28f574",
    "gen_ai.operation.name": "chat",
    "gen_ai.system": "openai",
    "gen_ai.request.model": "RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8",
    "gen_ai.request.temperature": "0.0",
    "gen_ai.request.max_tokens": "256",
    "gen_ai.request.seed": "1234",
    "gen_ai.request.stop_sequences": "[\"Q:\", \"</s>\", \"<|im_end|>\"]",
    "server.address": "qwen3-next-80b-kserve-workload-svc.kserve-lab.svc.cluster.local",
    "server.port": "8000",
    "gen_ai.response.model": "RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8",
    "gen_ai.response.finish_reasons": "[\"stop\"]",
    "gen_ai.response.id": "chatcmpl-78179c79-bc3e-4770-8711-61008dcd1542",
    "gen_ai.usage.input_tokens": "63",
    "gen_ai.usage.output_tokens": "153",
    "mlflow.spanType": "CHAT_MODEL",
    "peer.service": "vllm",
    "mlflow.chat.tokenUsage": "{\"input_tokens\": 63, \"output_tokens\": 153, \"total_tokens\": 216}"
  }
}
```

**Duration:** 1.35 seconds (1,353,674,074 nanoseconds)

**Key fields:**
- `trace_id`: Links all spans in the same trace
- `span_id`: Unique identifier for this span
- `parent_span_id`: References parent span (creates hierarchy)
- `start_time_unix_nano` / `end_time_unix_nano`: Nanosecond precision timestamps
- `events`: Array of span events (empty in this case)
- `status.code`: STATUS_CODE_UNSET, OK, or ERROR
- `attributes`: All span metadata (GenAI conventions, token usage, server info)

#### Example 2: HTTP POST Span (Network Layer)

```json
{
  "trace_id": "Hzh8+oAz6G3Y5A1fZdfKlQ==",
  "span_id": "PVbHKKyWIAA=",
  "parent_span_id": "RQHhxZuVJyA=",
  "name": "POST",
  "start_time_unix_nano": 1772383022343216414,
  "end_time_unix_nano": 1772383022529114808,
  "events": [],
  "status": {
    "code": "STATUS_CODE_UNSET",
    "message": ""
  },
  "attributes": {
    "mlflow.traceRequestId": "tr-1f387cfa8033e86dd8e40d5f65d7ca95",
    "http.method": "POST",
    "http.url": "http://qwen3-next-80b-kserve-workload-svc.kserve-lab.svc.cluster.local:8000/v1/chat/completions",
    "http.status_code": "200",
    "peer.service": "vllm"
  }
}
```

**Duration:** 185.9 milliseconds (185,898,394 nanoseconds)

**Key fields:**
- `name`: HTTP method (POST, GET, etc.)
- `attributes.http.method`: HTTP verb
- `attributes.http.url`: Full request URL
- `attributes.http.status_code`: HTTP response code
- `attributes.peer.service`: Downstream service name (enables service graph)

#### Span Hierarchy Example

In a typical trace, spans form a parent-child hierarchy:

```
Trace: tr-b920c37547d7953abce2f1b92b28f574
├─ Span: llamastack request handler (parent)
│  ├─ Span: chat RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8 (CHAT_MODEL)
│  │  └─ Span: POST (HTTP request to vLLM)
│  └─ Span: response processing
```

The `parent_span_id` field creates this hierarchy, allowing MLflow and Jaeger to display waterfall views.

### What IS Being Captured

✅ **OpenTelemetry Span Attributes:**
- GenAI semantic conventions (`gen_ai.operation.name`, `gen_ai.request.model`, etc.)
- HTTP attributes (`http.method`, `http.url`, `http.status_code`)
- Service topology (`peer.service` for downstream services)
- Performance metrics (span duration, timestamps)
- Token usage (`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`)

✅ **LLM Metadata (from span attributes):**
- Model name, operation name, conversation ID
- Agent name, session ID, user ID
- Token usage (input, output, total)
- Source detection (may require custom tagging)

> **Note on Request/Response Content**: OpenTelemetry instrumentation can capture prompt/completion content via log records (when `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`), but this data is emitted as log events, not span attributes. MLflow's current trace ingestion only processes span attributes, so request/response previews are not populated in the UI today. This could be enabled in the future by configuring a LoggerProvider and routing logs to MLflow alongside traces.

### What's NOT Being Captured

❌ **Server-side metrics from vLLM:**
- No Istio sidecar in vLLM pod (KServe/Knative incompatibility)
- No OpenTelemetry instrumentation in vLLM service itself
- Only client-side perspective available

❌ **Infrastructure metrics:**
- GPU utilization (use Prometheus/Kubernetes metrics instead)
- Model loading time
- VRAM usage
- Batch processing details

❌ **vLLM internals:**
- Queue wait time
- Attention mechanism performance
- KV cache statistics

❌ **Database query content:**
- SQL statement text is captured but truncated to 200 characters
- Full query plans not captured

## Generating Enhanced and System Spans

### TL;DR - What's Already Working

✅ **Auto-instrumentation IS active and IS generating enhanced GenAI data**
- Every LLM call automatically creates spans with full GenAI semantic conventions
- `opentelemetry-instrumentation-openai-v2` captures model, tokens, temperature, finish reasons, etc.
- OTel Collector transforms inject `mlflow.spanType` and other metadata
- **No code changes required** - this is already deployed and operational

✅ **You only need manual instrumentation for custom application logic**
- Add spans for data retrieval, preprocessing, business logic
- Nest spans to show multi-step workflows
- LLM calls and HTTP requests are already fully instrumented

### Detailed Overview

The MLflow observability stack supports two levels of instrumentation:

1. **Auto-instrumentation** (via `opentelemetry-instrument`): **Already active** - Automatically captures HTTP requests and **full GenAI semantic conventions** for all LLM calls (model, tokens, temperature, etc.). **This is the primary source of MLflow UI data.**
2. **Enhanced spans** (manual instrumentation): Add **custom business logic spans** with application-specific attributes, events, and nested hierarchies

### Auto-Instrumentation (Already Active)

**This is already running in production** and generates the majority of data visible in MLflow UI.

LlamaStack pods use `opentelemetry-instrument` as the entrypoint to automatically instrument:

- **FastAPI HTTP requests** (via `opentelemetry-instrumentation-fastapi`)
- **OpenAI SDK calls** (via `opentelemetry-instrumentation-openai-v2`) - **Generates full GenAI semantic conventions**

**Current configuration:**
```dockerfile
ENTRYPOINT ["opentelemetry-instrument", "llama", "stack", "run"]
```

**What it automatically captures (no code changes required):**

**GenAI attributes (from `opentelemetry-instrumentation-openai-v2`):**
- `gen_ai.operation.name`: "chat", "embedding", etc.
- `gen_ai.system`: "openai"
- `gen_ai.request.model`: Full model name
- `gen_ai.request.temperature`, `gen_ai.request.max_tokens`, `gen_ai.request.seed`
- `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`
- `gen_ai.response.id`, `gen_ai.response.model`, `gen_ai.response.finish_reasons`
- `peer.service`: "vllm", "llamastack", etc.

**HTTP attributes (from `opentelemetry-instrumentation-fastapi`):**
- `http.method`, `http.url`, `http.status_code`
- `http.target`, `http.host`, `http.user_agent`

**These auto-generated attributes may be used by MLflow** for:
- Version display (from `gen_ai.request.model`)
- Token metrics (from `gen_ai.usage.input_tokens` / `output_tokens`)
- Trace identification (from span name)
- Service topology (from `peer.service`)

**You only need manual instrumentation for custom application logic**, not for LLM calls (those are already fully instrumented).

### Creating Enhanced Spans with Manual Instrumentation

**When to use manual instrumentation:**
- Add custom business logic spans (data retrieval, preprocessing, post-processing)
- Nest spans to show multi-step workflows
- Add application-specific attributes not captured by auto-instrumentation
- Track custom events and milestones

**You do NOT need manual instrumentation for:**
- LLM inference calls (already instrumented by `opentelemetry-instrumentation-openai-v2`)
- HTTP requests (already instrumented by `opentelemetry-instrumentation-fastapi`)

To add custom spans, use the OpenTelemetry Python SDK directly:

#### Step 1: Install OpenTelemetry SDK

```bash
pip install opentelemetry-api opentelemetry-sdk
```

#### Step 2: Get a tracer

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)
```

#### Step 3: Create custom spans

```python
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer(__name__)

# Create a span
with tracer.start_as_current_span("custom-operation") as span:
    # Add attributes
    span.set_attribute("user.id", "alice")
    span.set_attribute("session.id", "session-123")
    span.set_attribute("model.name", "llama-3-8b")

    # Add events
    span.add_event("Processing started", {
        "queue.size": 5,
        "cache.hit": True
    })

    # Your business logic here
    result = process_request()

    # Set status
    if result.success:
        span.set_status(Status(StatusCode.OK))
    else:
        span.set_status(Status(StatusCode.ERROR, "Processing failed"))
        span.record_exception(result.error)
```

#### Step 4: Nest spans for hierarchy

```python
with tracer.start_as_current_span("parent-operation") as parent:
    parent.set_attribute("operation.type", "batch")

    for item in batch:
        with tracer.start_as_current_span(f"process-item-{item.id}") as child:
            child.set_attribute("item.id", item.id)
            child.set_attribute("item.type", item.type)
            process_item(item)
```

### GenAI Semantic Conventions

For LLM operations, follow OpenTelemetry GenAI semantic conventions:

```python
with tracer.start_as_current_span("llm-inference") as span:
    # Request attributes
    span.set_attribute("gen_ai.operation.name", "chat")
    span.set_attribute("gen_ai.system", "openai")
    span.set_attribute("gen_ai.request.model", "gpt-4")
    span.set_attribute("gen_ai.request.temperature", 0.7)
    span.set_attribute("gen_ai.request.max_tokens", 512)

    # Conversation context
    span.set_attribute("gen_ai.conversation.id", "conv-abc123")
    span.set_attribute("gen_ai.agent.name", "customer-support-bot")

    # Make LLM call
    response = llm.chat(messages)

    # Response attributes
    span.set_attribute("gen_ai.response.id", response.id)
    span.set_attribute("gen_ai.response.model", response.model)
    span.set_attribute("gen_ai.response.finish_reasons", response.finish_reasons)

    # Token usage
    span.set_attribute("gen_ai.usage.input_tokens", response.usage.prompt_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", response.usage.completion_tokens)
```

**These attributes are captured in span data** and may be used for trace analysis:
- `gen_ai.conversation.id` → Session identifier
- `gen_ai.agent.name` → Agent/user identifier
- `gen_ai.request.model` → Model version
- `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` → Token usage metrics

### Complete Example: Custom Instrumented Function

```python
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer(__name__)

async def process_user_query(user_id: str, query: str, session_id: str):
    """Process a user query with full instrumentation."""

    with tracer.start_as_current_span("process-user-query") as span:
        # Add user context
        span.set_attribute("user.id", user_id)
        span.set_attribute("session.id", session_id)
        span.set_attribute("query.length", len(query))

        try:
            # Step 1: Retrieve context
            with tracer.start_as_current_span("retrieve-context") as ctx_span:
                ctx_span.set_attribute("retrieval.method", "vector-search")
                context = await retrieve_context(query)
                ctx_span.set_attribute("retrieval.results", len(context))
                ctx_span.add_event("Context retrieved", {
                    "chunks": len(context),
                    "avg_score": context.avg_score
                })

            # Step 2: Call LLM
            with tracer.start_as_current_span("llm-inference") as llm_span:
                # GenAI semantic conventions
                llm_span.set_attribute("gen_ai.operation.name", "chat")
                llm_span.set_attribute("gen_ai.system", "openai")
                llm_span.set_attribute("gen_ai.request.model", "llama-3-70b")
                llm_span.set_attribute("gen_ai.conversation.id", session_id)
                llm_span.set_attribute("gen_ai.agent.name", "rag-assistant")

                response = await llm.chat(
                    messages=[
                        {"role": "system", "content": context},
                        {"role": "user", "content": query}
                    ]
                )

                # Response attributes
                llm_span.set_attribute("gen_ai.usage.input_tokens", response.usage.prompt_tokens)
                llm_span.set_attribute("gen_ai.usage.output_tokens", response.usage.completion_tokens)
                llm_span.set_attribute("gen_ai.response.finish_reasons", response.finish_reasons)

            # Step 3: Post-process
            with tracer.start_as_current_span("post-process") as post_span:
                post_span.set_attribute("response.length", len(response.text))
                result = post_process(response)

            span.set_status(Status(StatusCode.OK))
            return result

        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise
```

**This will create a trace with:**
- Parent span: `process-user-query` (with user context)
- Child span 1: `retrieve-context` (with retrieval metrics)
- Child span 2: `llm-inference` (with GenAI attributes from auto-instrumentation)
- Child span 3: `post-process` (with result metrics)

### Verifying Custom Spans in MLflow

After creating custom spans:

1. **Check MLflow UI:**
   - Go to `http://mlflow.<CLUSTER_IP>.nip.io`
   - Navigate to Experiments → llamastack-traces → Traces tab
   - Find your trace by timestamp or session ID
   - Verify waterfall view shows span hierarchy

2. **Query database directly:**
```bash
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U postgres -d mlflow -c "
    SELECT name, type, content::json->'attributes'->'session.id'
    FROM spans
    WHERE content::json->'attributes'->>'session.id' = 'session-123'
    ORDER BY start_time_unix_nano DESC
    LIMIT 10;
  "
```

### Best Practices

✅ **DO:**
- Use GenAI semantic conventions for LLM operations
- Add `user.id`, `session.id`, and `conversation.id` attributes
- Create nested spans for multi-step operations
- Set span status (`OK` or `ERROR`) and record exceptions
- Add events for significant milestones within a span

❌ **DON'T:**
- Capture sensitive data (passwords, API keys, PII) in attributes
- Create spans for operations < 1ms (noise)
- Nest spans > 10 levels deep (readability)
- Add > 50 attributes per span (performance)

### Data Flow

```
LLaMA Stack (OpenTelemetry SDK auto-instrumentation)
  ↓ Captures outbound HTTP calls
  ↓ Tags with peer.service="vllm"
  ↓
OTel Collector :4317/:4318
  ↓ Transform processor (adds/modifies attributes)
  ↓ Batch processor
  ↓ Fan-out to exporters
  ↓
MLflow /v1/traces
  ↓
PostgreSQL spans table
  ↓ Schema: trace_id, span_id, name, type, content (JSON)
```

### Querying Trace Data Directly

For advanced analysis beyond the MLflow UI, query PostgreSQL directly:

#### Connect to database:

```bash
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U postgres -d mlflow
```

#### Count spans by type:

```sql
SELECT COUNT(*) as count, type
FROM spans
WHERE content LIKE '%vllm%'
GROUP BY type
ORDER BY count DESC;
```

#### Get recent vLLM spans with latency:

```sql
SELECT
  to_timestamp(start_time_unix_nano/1000000000.0) as span_time,
  name,
  duration_ns/1000000 as duration_ms
FROM spans
WHERE content LIKE '%vllm%'
ORDER BY start_time_unix_nano DESC
LIMIT 10;
```

#### Extract specific attributes from span JSON:

```sql
SELECT
  name,
  content::json->'attributes'->'gen_ai.usage.input_tokens' as input_tokens,
  content::json->'attributes'->'gen_ai.usage.output_tokens' as output_tokens,
  content::json->'attributes'->'peer.service' as peer_service
FROM spans
WHERE content LIKE '%vllm%'
  AND type = 'CHAT_MODEL'
LIMIT 5;
```

#### Find spans by peer.service tag:

```sql
SELECT COUNT(*) as vllm_spans
FROM spans
WHERE content::json->'attributes'->>'peer.service' = 'vllm';
```

### Spans Table Schema

```sql
\d spans
```

| Column | Type | Description |
|--------|------|-------------|
| trace_id | varchar(50) | Unique trace identifier |
| experiment_id | integer | MLflow experiment ID (foreign key) |
| span_id | varchar(50) | Unique span identifier |
| parent_span_id | varchar(50) | Parent span ID (for nested spans) |
| name | text | Span name (e.g., "POST", "chat RedHat...") |
| type | varchar(500) | Span type (e.g., "CHAT_MODEL", null for HTTP) |
| status | varchar(50) | Status code (UNSET, OK, ERROR) |
| start_time_unix_nano | bigint | Start timestamp in nanoseconds |
| end_time_unix_nano | bigint | End timestamp in nanoseconds |
| duration_ns | bigint | Calculated duration (end - start) |
| content | text | JSON object with all span attributes |

**Primary key:** (trace_id, span_id)

**Indexes:**
- `index_spans_experiment_id`
- `index_spans_experiment_id_duration`
- `index_spans_experiment_id_status_type`

### Service Graph Visibility

The `peer.service: "vllm"` tag enables:

✅ **Kiali service topology:** Shows llamastack → vllm connection with live traffic metrics

✅ **Tempo service graph:** Query and visualize service relationships via Grafana

✅ **Service filtering:** Query traces by downstream service

For animated service topology visualization, see [Kiali documentation](../kiali/README.md).

### Performance Baselines

Based on observed trace data:

| Metric | Observed Range | Notes |
|--------|----------------|-------|
| End-to-end latency | 1.35s - 2.6s | Full request/response cycle |
| HTTP overhead | 13ms - 369ms | Network + protocol only |
| Input tokens | 57 - 94 tokens | Typical user prompts |
| Output tokens | 153 - 256 tokens | Model responses |
| Finish reasons | "stop", "length" | Natural stop vs max_tokens hit |

## Troubleshooting

### Pod Not Starting

Check pod events:

```bash
kubectl describe pod -n catalystlab-shared -l app=mlflow
```

Common issues:
- PVC not binding (check storage provisioner)
- Secret not found (verify `pgvector-cluster-app` exists)
- Image pull errors (check network/registry access)

### Database Connection Errors

Check logs for PostgreSQL connection errors:

```bash
kubectl logs -n catalystlab-shared -l app=mlflow | grep -i postgres
```

Verify the database exists:

```bash
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U postgres -c '\l' | grep mlflow
```

### 403 DNS Rebinding Errors

If API calls return 403 with "DNS rebinding" error, verify `--allowed-hosts` includes all required variants:

```bash
kubectl get deployment mlflow -n catalystlab-shared -o yaml | grep allowed-hosts
```

Should include:
```
--allowed-hosts=mlflow.<CLUSTER_IP>.nip.io,mlflow.catalystlab-shared.svc.cluster.local,mlflow.catalystlab-shared.svc.cluster.local:5000,localhost,localhost:5000
```

### Gateway API Errors

If you see store initialization errors in logs, verify `MLFLOW_TRACKING_URI` environment variable is set:

```bash
kubectl get deployment mlflow -n catalystlab-shared -o yaml | grep MLFLOW_TRACKING_URI
```

Should be set to the same value as `--backend-store-uri`.

### Traces Not Appearing

Check OTel Collector logs:

```bash
kubectl logs -n catalystlab-shared -l app=otel-collector
```

Verify the collector can reach MLflow:

```bash
kubectl exec -n catalystlab-shared -l app=otel-collector -- \
  wget -qO- http://mlflow.catalystlab-shared.svc.cluster.local:5000/health
```

Check that LLaMA Stack is sending traces:

```bash
kubectl logs -n catalystlab-shared -l app=llamastack | grep -i otel
```

## Critical Configuration Notes

### 1. DNS Rebinding Protection

MLflow 3.x uses `fnmatch` for DNS rebinding protection and **does not strip ports** from the Host header. You must include both hostname and hostname:port variants in `--allowed-hosts`.

**Incorrect:**
```
--allowed-hosts=mlflow.catalystlab-shared.svc.cluster.local
```

**Correct:**
```
--allowed-hosts=mlflow.catalystlab-shared.svc.cluster.local,mlflow.catalystlab-shared.svc.cluster.local:5000
```

### 2. MLFLOW_TRACKING_URI Environment Variable

MLflow 3.x has a bug where FastAPI gateway workers resolve the tracking store from the `MLFLOW_TRACKING_URI` environment variable, **NOT** from the `--backend-store-uri` CLI flag.

Always set both:
```yaml
command:
  - --backend-store-uri=postgresql://...
env:
  - name: MLFLOW_TRACKING_URI
    value: "postgresql://..."
```

### 3. Trace Endpoint

Use `/v1/traces` for OTLP ingestion, **NOT** `/api/2.0/mlflow/traces`.

The OTel Collector's `otlphttp` exporter automatically appends `/v1/traces` to the endpoint URL.

### 4. Experiment ID Bootstrap

The OTel Collector requires an experiment ID before it can forward traces. This creates a bootstrap sequence:

1. Deploy MLflow
2. Create experiment via API
3. Get experiment ID
4. Update OTel Collector config with ID
5. Deploy OTel Collector

## Architecture

```
LLaMA Stack ──(OTel SDK)──► OTel Collector ──(otlphttp)──┬──► MLflow /v1/traces
  :8321                        :4317/:4318                │        :5000
  (opentelemetry-instrument)                             │          │
                                                         │  ┌───────┴────────┐
                                                         │  │                │
                                                         │  ▼                ▼
                                                         │ PostgreSQL   PVC (artifacts)
                                                         │  (mlflow)   /mlflow/artifacts
                                                         │
                                                         └──► Tempo Distributor
                                                              (distributed tracing)
```

**Data flow:**
1. **LLaMA Stack** emits OpenTelemetry spans during inference (via `opentelemetry-instrument` auto-instrumentation with GenAI semantic conventions)
2. **OTel Collector** receives spans on gRPC (4317) or HTTP (4318), applies transformations (probe filtering, spanType injection)
3. **OTel Collector** fans out to MLflow (`/v1/traces` OTLP endpoint) and Tempo (distributed tracing backend)
4. **MLflow** stores trace metadata in PostgreSQL (`mlflow` database) and artifacts in PVC
5. Users access traces and experiments via **MLflow UI** (port 5000)

## Tempo Integration

> **Note**: Tempo is a complementary distributed tracing backend. MLflow provides full trace functionality independently.

Grafana Tempo is deployed alongside MLflow to provide long-term trace storage and service graph visualization via Grafana:

| Feature | MLflow | Tempo |
|---------|--------|--------|
| Waterfall/Timeline View | ✅ Excellent | ✅ Via Grafana |
| Service Dependency Graph | ❌ Not available | ✅ Via Grafana |
| Experiment Tracking | ✅ Full support | ❌ Not available |
| Web UI | ✅ Built-in | ❌ API-only (use Grafana) |
| Long-term Storage | ✅ PostgreSQL | ✅ Object storage |

### When to Use Each Tool

- **Use MLflow for**: Experiment tracking, waterfall views, LLM-specific metadata (tokens, prompts, responses)
- **Use Tempo for**: Service architecture visualization, distributed trace correlation, long-term trace retention

### Architecture with Tempo

```
LLaMA Stack → OTel Collector ─┬─► MLflow (waterfall views, experiments, LLM metadata)
                               └─► Tempo (distributed tracing, service graphs)
```

Both systems receive the same traces from the OTel Collector via fan-out configuration.

### Deployment

Tempo is already deployed in `catalystlab-shared` namespace. See [../tempo/README.md](../tempo/README.md) for configuration details.

### Access URLs

- **MLflow UI**: http://mlflow.<CLUSTER_IP>.nip.io
- **Tempo API**: http://tempo.<CLUSTER_IP>.nip.io
- **Grafana** (for Tempo visualization): Configure Tempo as a data source in Grafana

### Tempo API Endpoints

Tempo has no web UI. Access traces via API or Grafana:

```bash
# Health check
curl http://tempo.<CLUSTER_IP>.nip.io/api/echo

# Get trace by ID
curl http://tempo.<CLUSTER_IP>.nip.io/api/traces/{traceID}

# Search traces
curl http://tempo.<CLUSTER_IP>.nip.io/api/search
```

## Operational Notes

### Current State (as of 2026-03-01)

| Property | Value |
|----------|-------|
| Namespace | `catalystlab-shared` |
| Image | `ghcr.io/mlflow/mlflow:latest-full` |
| Internal URL | `mlflow.catalystlab-shared.svc.cluster.local:5000` |
| Backend store | PostgreSQL `mlflow` database on `pgvector-cluster-rw` |
| Artifact store | PVC `/mlflow/artifacts` (10Gi, `local-path`) |
| Experiment | `llamastack-traces` -- ID **1** (active, receiving traces) |

### Known Limitations and Current Status

❌ **NOT CAPTURED: Request/response preview columns**
- OpenTelemetry instrumentation can capture prompt/completion content via log records (when `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`)
- However, this data is emitted as log events, not span attributes
- MLflow's trace ingestion only processes span attributes, so `trace_info.request_preview` / `response_preview` remain empty
- **Previous middleware approach was abandoned** - too complex and not supported upstream
- Could be enabled in future by configuring LoggerProvider and routing logs to MLflow

❓ **UNKNOWN: MLflow UI metadata columns (Source, Version, Tokens, User, Session)**
- **Previous enrichment service was abandoned** along with middleware effort (March 17, 2026)
- MLflow may natively extract some metadata from GenAI span attributes
- Current population status of these UI columns needs verification
- See section below for verification steps

✅ **WORKING: Span type attribute**
- OTel Collector OTTL transform injects `mlflow.spanType` from `gen_ai.operation.name`
- Populated before trace reaches MLflow

✅ **WORKING: Token usage**
- `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` captured by OpenTelemetry instrumentation
- `mlflow.chat.tokenUsage` injected by OTel Collector transform
- Token metrics available in span attributes for analysis

⚠️ **Remaining limitations:**
- **No server-side vLLM metrics**: Only client-side perspective (no Istio sidecar in KServe pods)
- **Truncated previews**: Request/Response limited to 1000 characters due to database column size
- **Source detection**: Depends on `peer.service` attribute being set by OTel Collector

### OTel Collector Ownership

The OTel collector config for `catalystlab-shared` is managed in [`../otel-collector/otel-collector.yaml`](../otel-collector/otel-collector.yaml). Do not modify the simplified copy at `mlflow/otel-collector-config.yaml` -- it is deprecated and missing critical processors.

## References

- [MLflow Documentation](https://mlflow.org/docs/latest/index.html)
- [CloudNativePG Documentation](https://cloudnative-pg.io/documentation/)
- [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
- [OpenTelemetry Python SDK](https://opentelemetry.io/docs/languages/python/)
- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [LLaMA Stack](https://github.com/meta-llama/llama-stack)
- [Grafana Tempo](https://grafana.com/docs/tempo/latest/)
