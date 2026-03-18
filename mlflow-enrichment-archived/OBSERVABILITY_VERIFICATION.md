# Observability Stack Verification & Optimization

## Current Architecture Analysis

Based on code analysis of your repository, here's the actual data flow:

```
┌─────────────────────────────────────────────────────────────┐
│          Trace Sources (LlamaStack, VLLM, Agents)           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
              OTel Collector :4317/:4318
              ┌─────────────────────────┐
              │ Receivers: OTLP         │
              │ Processors:             │
              │  - filter/drop-probes   │
              │  - transform (OTTL)     │
              │  - batch                │
              │ Exporters:              │
              │  - otlp_http (MLflow)   │
              │  - otlp_grpc (Tempo)    │
              │  - spanmetrics          │
              │  - servicegraph         │
              └─────────┬───────┬───────┘
                        │       │
         ┌──────────────┘       └──────────────┐
         │                                     │
         ▼                                     ▼
    MLflow :5000                         Tempo :4317
    ┌──────────────┐                    ┌──────────────┐
    │ OTLP /v1/traces                   │ Distributor  │
    │      ↓                             │      ↓       │
    │ PostgreSQL                         │ Ingester     │
    │  - spans                           │      ↓       │
    │  - trace_info                      │ Storage      │
    │  - trace_tags                      └──────┬───────┘
    │  - trace_request_metadata                 │
    └──────┬───────┘                            │
           │                                    │
           │ ┌──────────────────────────────────┘
           │ │
           ▼ ▼
    ┌─────────────────────────────────┐
    │    Enrichment Processes          │
    │                                  │
    │ 1. Enrichment Service            │
    │    - Polls PostgreSQL every 30s  │
    │    - Extracts gen_ai.* from      │
    │      spans.content JSONB         │
    │    - Backfills trace_tags,       │
    │      trace_info, metadata        │
    │                                  │
    │ 2. LlamaStack Middleware         │
    │    - Intercepts FastAPI requests │
    │    - Writes directly to          │
    │      PostgreSQL tables           │
    │    - Bypasses MLflow API         │
    └──────────────────────────────────┘
           │
           ▼
    ┌─────────────────┐
    │  Kiali          │
    │  (reads Tempo)  │
    └─────────────────┘
```

## Component Analysis

### 1. Enrichment Service ([mlflow/enrichment-service.py](mlflow/enrichment-service.py))

**What it does:**
- Polls MLflow PostgreSQL database every 30 seconds
- Finds traces with `NULL` request_preview or response_preview
- Extracts attributes from `spans.content` JSONB field
- Backfills three tables:
  - `trace_tags` - MLflow UI column data (User, Session, Trace Name, Source, Version, Token counts)
  - `trace_info` - Request/Response previews (truncated to 1000 chars)
  - `trace_request_metadata` - Additional metadata (model, operation, enrichment_source)

**Fields populated:**
```sql
-- trace_tags
mlflow.user                 -- from gen_ai.agent.name or "system"
mlflow.session              -- from gen_ai.conversation.id or "default"
mlflow.traceName            -- from root span name
mlflow.version              -- static "v1.0"
mlflow.source.name          -- detected: "kagent", "llamastack", "vllm", "http"
mlflow.source.type          -- "GENAI" or "HTTP"
mlflow.promptTokens         -- from gen_ai.usage.input_tokens
mlflow.completionTokens     -- from gen_ai.usage.output_tokens
mlflow.totalTokens          -- calculated sum

-- trace_info
request_preview             -- from gen_ai.prompt.1.content or http.method+url
response_preview            -- from gen_ai.completion.0.content or http.status_code

-- trace_request_metadata
enrichment_source: "enrichment-service"
model: from gen_ai.request.model
operation: from gen_ai.operation.name
```

**Source attributes extracted:**
- `gen_ai.prompt.1.content` → request_preview
- `gen_ai.completion.0.content` → response_preview
- `gen_ai.conversation.id` → session
- `gen_ai.agent.name` → user
- `gen_ai.request.model` → model
- `gen_ai.operation.name` → operation
- `gen_ai.usage.input_tokens` → promptTokens
- `gen_ai.usage.output_tokens` → completionTokens
- Fallback: `http.*` attributes for non-GenAI traces

**Performance characteristics:**
- ⚠️ 30-second polling delay
- ⚠️ Processes 100 traces per cycle
- ⚠️ 10 retries with 0.5s delay on failure
- ✅ Uses `ON CONFLICT DO UPDATE` for idempotency

### 2. LlamaStack MLflow Middleware ([llamastack/mlflow_middleware.py](llamastack/mlflow_middleware.py))

**What it does:**
- FastAPI middleware that intercepts `/v1/chat/completions`, `/v1/embeddings`, `/v1/agents` requests
- Creates MLflow spans using MLflow Python SDK
- Writes metadata directly to PostgreSQL (bypassing MLflow API)
- Background task with 10 retries @ 500ms intervals

**Fields populated:**
```sql
-- trace_tags (via direct SQL INSERT)
mlflow.user                 -- from X-User-ID header or "system"
mlflow.session              -- from X-Session-ID header or "llamastack-default"
mlflow.traceName            -- constructed from endpoint + model
version                     -- extracted from model name
mlflow.source.name          -- static "llamastack"
mlflow.source.type          -- static "PROMPT_ENGINEERING"

-- trace_info (via direct SQL UPDATE)
request_preview             -- last user message content (1000 chars)
response_preview            -- assistant response content (1000 chars)

-- trace_request_metadata
mlflow.trace.user
mlflow.trace.session
mlflow.trace.name
mlflow.trace.version
```

**Why it exists:**
Per [otel-collector/README.md](otel-collector/README.md#L48-L56):
> **Root cause:** The openai-v2 instrumentation emits prompt/response content via OTel EventLogger (log records), not as span attributes or span events. MLflow does not accept OTLP logs (`/v1/logs` returns 404). Cross-signal log-to-span merging is not possible in the OTel Collector.

**Performance characteristics:**
- ⚠️ Intercepts every request (adds latency)
- ⚠️ Background task with 5-second total retry window (10 × 500ms)
- ⚠️ Direct PostgreSQL writes (bypasses MLflow's internal logic)
- ❌ Creates inconsistency (two writers to same tables)

### 3. OTel Collector Transform Processor ([otel-collector/otel-collector.yaml](otel-collector/otel-collector.yaml))

**What it does:**
```yaml
transform:
  trace_statements:
    - context: span
      statements:
        # MLflow span type injection
        - set(attributes["mlflow.spanType"], "CHAT_MODEL") where attributes["gen_ai.operation.name"] == "chat"
        - set(attributes["mlflow.spanType"], "LLM") where attributes["gen_ai.operation.name"] == "text_completion"

        # MLflow trace metadata (partial)
        - set(attributes["mlflow.spanInputs"], attributes["gen_ai.prompt.1.content"]) where ...
        - set(attributes["mlflow.spanOutputs"], attributes["gen_ai.completion.0.content"]) where ...
        - set(attributes["session.id"], attributes["gen_ai.conversation.id"]) where ...
        - set(attributes["user.id"], attributes["gen_ai.agent.name"]) where ...

        # Service graph edges
        - set(attributes["peer.service"], "vllm") where ...
```

**Fields populated:**
- `mlflow.spanType` - for MLflow UI "Span Type" column
- `mlflow.spanInputs` - partial (only on child spans, not root)
- `mlflow.spanOutputs` - partial (only on child spans, not root)
- `session.id` - mapped from gen_ai.conversation.id
- `user.id` - mapped from gen_ai.agent.name
- `peer.service` - for Kiali/Tempo service graphs

**Current gaps:**
- ❌ Does NOT set `mlflow.user`, `mlflow.session`, `mlflow.traceName`
- ❌ Does NOT set `mlflow.source.name`, `mlflow.source.type`
- ❌ Does NOT set `mlflow.promptTokens`, `mlflow.completionTokens`, `mlflow.totalTokens`
- ❌ Does NOT set `mlflow.version`
- ⚠️ Sets `mlflow.spanInputs`/`mlflow.spanOutputs` only on child spans (not root)

## Critical Question: Does MLflow Auto-Populate Tables?

**The optimization depends on:** Does MLflow's OTLP ingestion (`POST /v1/traces`) automatically populate `trace_tags` and `trace_info` tables when it receives spans with `mlflow.*` attributes?

### Test Procedure (Run on Cluster)

```bash
# Run the test script
chmod +x test-mlflow-otlp-ingestion.sh
./test-mlflow-otlp-ingestion.sh
```

This script:
1. Sends a test span with ALL `mlflow.*` attributes through OTel Collector
2. Waits 5 seconds for MLflow ingestion
3. Queries PostgreSQL to check if `trace_tags` and `trace_info` were auto-populated
4. Provides clear verdict

### Expected Outcomes

**Scenario A: MLflow DOES auto-populate**
- ✅ `trace_tags` table populated from `mlflow.user`, `mlflow.session`, etc.
- ✅ `trace_info` table populated from `mlflow.spanInputs`, `mlflow.spanOutputs`
- **Conclusion:** Enrichment service is redundant
- **Action:** Eliminate enrichment service, enhance OTel Collector transform processor

**Scenario B: MLflow does NOT auto-populate**
- ❌ `trace_tags` table empty (despite `mlflow.*` attributes in span)
- ❌ `trace_info` table has NULL previews
- **Conclusion:** Enrichment service is required
- **Action:** Keep enrichment service, remove middleware (redundant)

## Verification Commands (Run on Cluster)

### 1. Check Enrichment Service Activity

```bash
# Get enrichment service pod
kubectl get pods -n catalystlab-shared -l app=mlflow-enrichment

# Check logs for enrichment activity
kubectl logs -n catalystlab-shared -l app=mlflow-enrichment --tail=100 | grep "Successfully enriched"

# Count enriched traces
kubectl exec -n catalystlab-shared <postgres-pod> -- psql -U postgres -d mlflow -c \
  "SELECT COUNT(*) FROM trace_request_metadata WHERE key = 'enrichment_source';"
```

**Expected:** Should show traces being enriched every 30 seconds.

### 2. Verify MLflow Field Population

```bash
# Connect to PostgreSQL
POSTGRES_POD=$(kubectl get pods -n catalystlab-shared -l cnpg.io/cluster=pgvector-cluster -o jsonpath='{.items[0].metadata.name}')

# Check trace_tags (MLflow UI columns)
kubectl exec -n catalystlab-shared $POSTGRES_POD -- psql -U postgres -d mlflow -c \
  "SELECT key, COUNT(*) FROM trace_tags GROUP BY key ORDER BY key;"

# Check trace_info (request/response previews)
kubectl exec -n catalystlab-shared $POSTGRES_POD -- psql -U postgres -d mlflow -c \
  "SELECT
    COUNT(*) as total_traces,
    COUNT(request_preview) as with_request,
    COUNT(response_preview) as with_response
   FROM trace_info;"

# Check specific trace
kubectl exec -n catalystlab-shared $POSTGRES_POD -- psql -U postgres -d mlflow -c \
  "SELECT request_id, LEFT(request_preview, 50) as request_sample
   FROM trace_info
   WHERE request_preview IS NOT NULL
   LIMIT 5;"
```

**Expected:**
- `trace_tags`: Should have mlflow.user, mlflow.session, mlflow.traceName, mlflow.source.*, token fields
- `trace_info`: Should have populated request_preview and response_preview
- If empty: enrichment service not working or no traces yet

### 3. Verify VLLM → OTel Collector

```bash
# Check for vLLM spans in database
kubectl exec -n catalystlab-shared $POSTGRES_POD -- psql -U postgres -d mlflow -c \
  "SELECT COUNT(*) as vllm_spans
   FROM spans
   WHERE content::json->'attributes'->>'peer.service' = 'vllm';"

# Check CHAT_MODEL spans (GenAI semantic conventions)
kubectl exec -n catalystlab-shared $POSTGRES_POD -- psql -U postgres -d mlflow -c \
  "SELECT COUNT(*) as chat_model_spans
   FROM spans
   WHERE type = 'CHAT_MODEL';"

# Sample vLLM span attributes
kubectl exec -n catalystlab-shared $POSTGRES_POD -- psql -U postgres -d mlflow -c \
  "SELECT
     name,
     content::json->'attributes'->>'gen_ai.request.model' as model,
     content::json->'attributes'->>'gen_ai.usage.input_tokens' as input_tokens
   FROM spans
   WHERE content::json->'attributes'->>'peer.service' = 'vllm'
   LIMIT 3;"
```

**Expected:**
- vLLM spans > 0 (if vLLM is being called)
- CHAT_MODEL spans > 0 (indicates GenAI semantic conventions working)
- Should see model name and token usage

### 4. Verify LlamaStack → OTel Collector

```bash
# Check LlamaStack OTEL configuration
kubectl get deployment llamastack -n catalystlab-shared -o yaml | grep OTEL

# Check LlamaStack spans
kubectl exec -n catalystlab-shared $POSTGRES_POD -- psql -U postgres -d mlflow -c \
  "SELECT COUNT(*) as llamastack_spans
   FROM spans
   WHERE name LIKE '%POST%' OR name LIKE '%chat%'
   ORDER BY start_time_unix_nano DESC;"

# Check OTel Collector logs
kubectl logs -n catalystlab-shared deployment/otel-collector --tail=100 | grep -i "export\|otlp"
```

**Expected:**
- `OTEL_EXPORTER_OTLP_ENDPOINT` should be set to `http://otel-collector.catalystlab-shared.svc.cluster.local:4317`
- Should see POST/chat spans
- OTel Collector logs should show exports to MLflow and Tempo

### 5. Verify Tempo Capture

```bash
# Check Tempo distributor
kubectl get deployment tempo-distributor -n catalystlab-shared
kubectl logs -n catalystlab-shared deployment/tempo-distributor --tail=50 | grep -i "span\|batch"

# Check Tempo ingester
kubectl get statefulset tempo-ingester -n catalystlab-shared
kubectl logs -n catalystlab-shared tempo-ingester-0 --tail=50 | grep -i "block\|wal"

# Verify OTel Collector → Tempo exporter
kubectl get configmap otel-collector-config -n catalystlab-shared -o yaml | grep -A 5 "tempo"
```

**Expected:**
- Tempo distributor and ingester pods running
- Distributor logs show trace ingestion
- Ingester logs show blocks being written
- OTel Collector config has `otlp_grpc/tempo` exporter

### 6. Verify Kiali Integration

```bash
# Check Kiali deployment
kubectl get deployment kiali -n istio-system

# Check Kiali Tempo configuration
kubectl get configmap kiali -n istio-system -o yaml | grep -A 10 "tracing:"

# Test Kiali → Tempo connectivity
kubectl exec -n istio-system deployment/kiali -- \
  curl -s -o /dev/null -w "%{http_code}" \
  http://tempo-query-frontend.catalystlab-shared.svc.cluster.local:3200
```

**Expected:**
- Kiali configured with `provider: tempo`
- `in_cluster_url` points to tempo-query-frontend
- Connectivity test returns 200 or 404 (both indicate reachability)

## Optimization Recommendations

### Option 1: If MLflow Auto-Populates (Scenario A)

**Eliminate redundancy:**

1. **Remove** enrichment service:
   ```bash
   kubectl delete deployment mlflow-enrichment -n catalystlab-shared
   kubectl delete configmap mlflow-enrichment-script -n catalystlab-shared
   ```

2. **Enhance** OTel Collector transform processor to add ALL mlflow.* attributes:
   ```yaml
   - set(attributes["mlflow.user"], attributes["gen_ai.agent.name"]) where attributes["gen_ai.agent.name"] != nil
   - set(attributes["mlflow.user"], "system") where attributes["gen_ai.agent.name"] == nil
   - set(attributes["mlflow.session"], attributes["gen_ai.conversation.id"]) where ...
   - set(attributes["mlflow.traceName"], span.name)
   - set(attributes["mlflow.promptTokens"], attributes["gen_ai.usage.input_tokens"]) where ...
   - set(attributes["mlflow.completionTokens"], attributes["gen_ai.usage.output_tokens"]) where ...
   # ... etc
   ```

3. **Remove** LlamaStack middleware (creates inconsistency):
   - Remove mlflow_middleware.py from container
   - Remove middleware registration from LlamaStack startup

**Result:** Single source of truth (OTel Collector), <1s latency, no polling overhead

### Option 2: If MLflow Does NOT Auto-Populate (Scenario B)

**Keep enrichment, optimize where possible:**

1. **Keep** enrichment service (required to populate MLflow UI)

2. **Remove** LlamaStack middleware (redundant with enrichment service):
   - Both write to same tables
   - Enrichment service is more comprehensive
   - Middleware adds request latency

3. **Enhance** OTel Collector to reduce enrichment service work:
   - Add more mlflow.* attributes at OTel level
   - Reduces what enrichment service needs to extract from JSONB

**Result:** Single enrichment mechanism, reduced middleware overhead

## Current Issues

### 1. Duplicate Writers

**Problem:** Both enrichment service AND middleware write to `trace_tags`, `trace_info`:
- Enrichment service polls every 30s, extracts from spans.content
- Middleware intercepts requests, writes immediately

**Risk:**
- Race conditions
- Inconsistent data (different values from two sources)
- Wasted CPU (two processes doing similar work)

**Solution:** Eliminate one writer (depends on test results)

### 2. 30-Second Enrichment Delay

**Problem:** Traces appear in MLflow UI with empty columns for up to 30 seconds

**Impact:**
- Poor UX (users see incomplete data)
- Makes debugging harder (missing context)

**Solution:**
- If MLflow auto-populates: eliminate enrichment service entirely
- If not: reduce POLL_INTERVAL to 5s (acceptable tradeoff)

### 3. Request/Response Content Not in Span Attributes

**Root cause:** `opentelemetry-instrumentation-openai-v2` emits content via OTel EventLogger (logs), not span attributes

**Current workaround:** Enrichment service extracts from JSONB

**Proper fix:**
- Upgrade to instrumentation version that supports `SPAN_AND_EVENT` mode
- Or: Use OTel Logs Receiver (MLflow needs to support `/v1/logs`)
- Or: Keep enrichment service as architectural workaround

## Recommended Architecture (Assuming Scenario A)

```
LlamaStack/VLLM
    │
    ├─ OpenTelemetry auto-instrumentation
    │  (opentelemetry-instrumentation-openai-v2)
    │
    ▼
OTel Collector
    │
    ├─ filter/drop-probes (remove health checks)
    │
    ├─ transform processor (SINGLE SOURCE OF ENRICHMENT)
    │  ├─ Extract gen_ai.* → mlflow.* attributes
    │  ├─ Set mlflow.user, mlflow.session, mlflow.traceName
    │  ├─ Set mlflow.source.name, mlflow.source.type
    │  ├─ Set mlflow.promptTokens, mlflow.completionTokens, mlflow.totalTokens
    │  ├─ Set mlflow.spanInputs, mlflow.spanOutputs (from gen_ai.* if available)
    │  └─ Set peer.service for service graphs
    │
    ├─ batch processor
    │
    ├──► MLflow :5000/v1/traces
    │    └─ Auto-populates trace_tags, trace_info from mlflow.* attributes
    │
    └──► Tempo :4317
         └─ Stores traces for Grafana/Kiali

Kiali → Tempo query-frontend → Shows service graphs + traces
```

**Benefits:**
- ✅ Single enrichment point (OTel Collector)
- ✅ Real-time (<1s latency)
- ✅ No database polling overhead
- ✅ Consistent data across MLflow and Tempo
- ✅ Simpler architecture (fewer moving parts)

## Next Steps

1. **Run the test:** `./test-mlflow-otlp-ingestion.sh` on the cluster
2. **Review results:** Does MLflow auto-populate tables?
3. **Choose path:**
   - **Scenario A:** Enhance OTel Collector, eliminate enrichment service + middleware
   - **Scenario B:** Keep enrichment service, remove middleware, enhance OTel where possible
4. **Update documentation:** Document the chosen architecture in this file

## Summary

Your observability stack has **three enrichment mechanisms** doing overlapping work:

1. **OTel Collector transform** - partial enrichment (mlflow.spanType, peer.service)
2. **Enrichment Service** - comprehensive enrichment (all mlflow UI fields), 30s polling delay
3. **MLflow Middleware** - request/response previews, immediate write, bypasses MLflow API

**The test will tell us:** Can we consolidate to just #1 (OTel Collector)?

**If yes:** Eliminate #2 and #3 → simpler, faster, more consistent
**If no:** Eliminate #3 (redundant), keep #2 (required) → reduce middleware overhead
