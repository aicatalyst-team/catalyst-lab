# Fix for Null Request/Response Previews in MLflow UI

## Problem

MLflow UI showed many traces with `null` values in Request and Response columns. This occurred because:

1. **OpenTelemetry semantic conventions** do NOT capture LLM prompt/completion content in span attributes
   - Content is emitted via EventLogger (not stored in OTLP traces)
   - Only metadata (model, tokens, status) is captured in attributes

2. **Database traces** from SQLAlchemy had no extraction logic
   - LlamaStack's internal DB queries created traces with db.* attributes
   - Enrichment service didn't handle these, leaving previews null

3. **No HTTP body capture** after middleware removal
   - Previous full middleware captured request/response bodies
   - New Option A architecture removed this entirely

## Root Cause

The GenAI semantic conventions (gen_ai.*) intentionally avoid putting large content in span attributes to prevent OTLP payload bloat. This is by design.

**What OpenTelemetry captures:**
- ✓ Model name (gen_ai.request.model)
- ✓ Token counts (gen_ai.usage.input_tokens/output_tokens)
- ✓ Operation name (gen_ai.operation.name)
- ✗ Prompt content (emitted via EventLogger, not in attributes)
- ✗ Completion content (emitted via EventLogger, not in attributes)

**MLflow expects:**
- trace_info.request_preview: actual prompt text
- trace_info.response_preview: actual completion text

## Solution

### Architecture Change

**Hybrid approach: Lightweight middleware + Enrichment service**

```
┌────────────────────────────────────────────┐
│          LlamaStack Pod                    │
│  ┌──────────────────────────────────────┐  │
│  │  Preview Middleware (NEW)            │  │
│  │  - Intercepts HTTP bodies            │  │
│  │  - Extracts prompt/completion        │  │
│  │  - Writes to trace_info only         │  │
│  └──────────────────────────────────────┘  │
│  ┌──────────────────────────────────────┐  │
│  │  OpenTelemetry Auto-Instrumentation │  │
│  │  - Creates spans                     │  │
│  │  - Captures metadata (gen_ai.*)      │  │
│  └──────────────────────────────────────┘  │
└────────────────────────────────────────────┘
                    │
                    ▼
            OTel Collector
                    │
                    ▼
┌────────────────────────────────────────────┐
│              MLflow                        │
│  ┌──────────────────────────────────────┐  │
│  │  OTLP Endpoint                       │  │
│  │  - Receives spans from collector     │  │
│  │  - Writes to PostgreSQL             │  │
│  └──────────────────────────────────────┘  │
└────────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────┐
│    Enrichment Service (ENHANCED)           │
│  - Extracts tags from span attributes      │
│  - Handles GenAI, HTTP, DB traces          │
│  - Writes to trace_tags/metadata           │
│  - Does NOT write previews (middleware)    │
└────────────────────────────────────────────┘
```

### Code Changes

#### 1. New Lightweight Preview Middleware

**File:** `llamastack/preview_middleware.py`

- Captures HTTP request/response bodies ONLY
- Extracts prompt from messages array
- Extracts completion from response choices
- Writes to `trace_info.request_preview` and `response_preview`
- Does NOT create spans
- Does NOT write to trace_tags
- Minimal dependencies (only psycopg2, no MLflow SDK)

#### 2. Enhanced Enrichment Service

**File:** `mlflow/enrichment-service.py` and `mlflow/enrichment-deployment.yaml`

**Added database trace handling:**
```python
# Extract db.* attributes (database query traces from SQLAlchemy/psycopg2)
if not extracted['prompt'] and 'db.statement' in attributes:
    db_system = attributes.get('db.system', 'database').strip('"')
    db_name = attributes.get('db.name', '').strip('"')
    db_statement = attributes.get('db.statement', '').strip('"')

    # Truncate long SQL statements
    if len(db_statement) > 200:
        db_statement = db_statement[:200] + "..."

    extracted['prompt'] = f"{db_system.upper()} {db_name}: {db_statement}"
    extracted['completion'] = "Query executed"
    extracted['trace_type'] = 'database'
```

**Added database source classification:**
```python
elif trace_type == 'database':
    source_type = 'DATABASE'
    source = 'llamastack'  # DB traces come from LlamaStack's SQLAlchemy
```

#### 3. Updated Containerfile

**File:** `llamastack/Containerfile.no-middleware`

- Copies preview_middleware.py into image
- Injects middleware using Python script (more robust than sed)
- Verifies injection succeeded
- Only adds psycopg2-binary (no MLflow SDK needed)

## Clear Separation of Concerns

| Component | Responsibility |
|-----------|---------------|
| **Preview Middleware** | HTTP body capture → trace_info.request_preview/response_preview |
| **Enrichment Service** | Span attributes → trace_tags + trace_request_metadata |
| **OTel Collector** | Span transformations (peer.service, mlflow.spanType) |

**What middleware does NOT do:**
- ✗ Create spans (OpenTelemetry handles this)
- ✗ Write to trace_tags (enrichment service handles this)
- ✗ Set MLflow experiments (not needed)
- ✗ Call MLflow SDK (avoids duplicate spans)

**What enrichment service does NOT do:**
- ✗ Capture HTTP bodies (can't access them from OTLP data)
- ✗ Write to trace_info.request_preview/response_preview (middleware handles this)

## Deployment Steps

### 1. Deploy Enhanced Enrichment Service

```bash
scp mlflow/enrichment-deployment.yaml root@<CLUSTER_IP>:/tmp/
ssh root@<CLUSTER_IP> 'kubectl apply -f /tmp/enrichment-deployment.yaml'
ssh root@<CLUSTER_IP> 'kubectl rollout restart deployment/mlflow-enrichment -n catalystlab-shared'
```

### 2. Build and Deploy LlamaStack with Preview Middleware

```bash
cd llamastack
podman build -f Containerfile.no-middleware -t quay.io/rh-ee-gtrotman/llamastack-starter:preview-middleware .
podman push quay.io/rh-ee-gtrotman/llamastack-starter:preview-middleware
ssh root@<CLUSTER_IP> 'kubectl set image deployment/llamastack -n catalystlab-shared llamastack=quay.io/rh-ee-gtrotman/llamastack-starter:preview-middleware'
ssh root@<CLUSTER_IP> 'kubectl rollout status deployment/llamastack -n catalystlab-shared'
```

### 3. Verify

**Test GenAI trace:**
```bash
curl -X POST http://llamastack.<CLUSTER_IP>.nip.io/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "vllm/RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8",  # pragma: allowlist secret
    "messages": [{"role": "user", "content": "Test preview capture"}],
    "max_tokens": 10
  }'

# Wait 5 seconds for middleware + 30 seconds for enrichment service
sleep 35

# Check MLflow UI - should show:
# Request: "Test preview capture"
# Response: actual completion text
# Source: vllm
# Version: Qwen3-Next-80B-A3B-Instruct-FP8
```

## Results

### Before Fix

```
MLflow UI:
- Request:  null
- Response: null
- Source:   unknown
- 113 traces with null previews
```

### After Fix

```
MLflow UI:
- Request:  "Test preview capture"
- Response: "I'm sorry, but I can't assist with"
- Source:   vllm
- Version:  Qwen3-Next-80B-A3B-Instruct-FP8
- Database traces showing: "POSTGRESQL llamastack: SELECT ..."
- < 20 traces remaining with null previews (edge cases)
```

## Why This Is Better Than Full Middleware

| Aspect | Full Middleware | Hybrid (Middleware + Service) |
|--------|----------------|-------------------------------|
| **Code complexity** | High (150+ lines) | Low (80 lines middleware) |
| **Dependencies** | MLflow SDK, psycopg2 | Only psycopg2 |
| **MLflow coupling** | Creates spans via SDK | No span creation |
| **Duplicate writes** | Yes (tags + metadata) | No (clear separation) |
| **Enrichment logic** | Duplicated in 2 places | Single source of truth |
| **Latency impact** | Medium (immediate write) | Low (background task) |
| **Maintenance** | 2 codebases to sync | 1 enrichment service |

## Trade-offs

**Why keep the middleware at all?**

Because **OpenTelemetry cannot capture HTTP bodies**. The semantic conventions intentionally avoid this to keep OTLP payloads lean. The only way to get prompt/completion content is to intercept the HTTP request/response.

**Could we eliminate the middleware entirely?**

Only if we accept that GenAI traces won't have request/response previews. This would break the MLflow UI UX for LLM tracing.

**Could we capture content in the enrichment service?**

No. By the time traces reach MLflow's PostgreSQL database, the HTTP request/response bodies are long gone. Only span attributes remain, and those don't contain content.

## Testing

Verified with:
- ✓ GenAI traces (LlamaStack → vLLM)
- ✓ Database traces (LlamaStack SQLAlchemy)
- ✓ HTTP traces (MCP, ingress)
- ✓ Token usage fields populated
- ✓ Source classification working
- ✓ Version extraction from model name
- ✓ Tempo receiving all spans
- ✓ Kiali service graphs showing llamastack → vllm edges
