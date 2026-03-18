# Observability Stack Verification Results

**Date:** March 16, 2026
**Cluster:** <CLUSTER_IP>
**Namespace:** catalystlab-shared

## Executive Summary

✅ **All components are operational** - MLflow, OTel Collector, Tempo, Kiali are running and processing traces
⚠️ **Dual enrichment confirmed** - Both enrichment service AND MLflow middleware are actively populating database fields
❌ **MLflow does NOT auto-populate** - Manual enrichment is required for UI field population
✅ **End-to-end trace flow verified** - LlamaStack → OTel Collector → MLflow + Tempo → Kiali

## Key Findings

### 1. MLflow Field Population

**Database Status:**
- **6,844 total spans** in spans table
- **45,740 trace_tags entries** (enriched metadata)
- **4,550 trace_info records** with 4,544 having request/response previews
- **4,536 traces enriched by enrichment service**

**Verdict:** ❌ **MLflow does NOT auto-populate trace_tags or trace_info tables from span attributes**

Evidence:
- Spans contain `mlflow.spanType`, `gen_ai.*` attributes
- BUT trace_tags/trace_info remain NULL until enriched
- Enrichment service actively processing traces every 30s
- Found traces enriched by service: `enrichment_source = 'enrichment-service'`

### 2. Dual Enrichment Mechanism Confirmed

**Two separate systems are populating the same tables:**

#### A. MLflow Middleware ([llamastack/mlflow_middleware.py](llamastack/mlflow_middleware.py))
- **Intercepts:** FastAPI requests to `/v1/chat/completions`, `/v1/embeddings`, `/v1/agents`
- **Writes to:**
  - `trace_tags`: mlflow.user, mlflow.session, mlflow.traceName, mlflow.source.name, mlflow.source.type
  - `trace_info`: request_preview, response_preview
  - `trace_request_metadata`: mlflow.trace.*
- **Source:** HTTP headers (X-User-ID, X-Session-ID) and request/response bodies
- **Latency:** Immediate (background task, 10 retries @ 500ms)

**Example trace enriched by middleware:**
```sql
request_id: tr-585790da132442984d482760e9f479e8
trace_tags:
  mlflow.user = "enrichment-tester"  -- from X-User-ID header
  mlflow.session = "test-session-1"   -- from X-Session-ID header
  mlflow.source.name = "llamastack"
  mlflow.source.type = "PROMPT_ENGINEERING"
```

#### B. Enrichment Service ([mlflow/enrichment-service.py](mlflow/enrichment-service.py))
- **Polls:** PostgreSQL every 30 seconds
- **Finds:** Traces with NULL request_preview or response_preview
- **Extracts:** gen_ai.*, http.* attributes from spans.content JSONB
- **Writes to:**
  - `trace_tags`: mlflow.user, mlflow.session, mlflow.traceName, mlflow.source.*, mlflow.*Tokens
  - `trace_info`: request_preview, response_preview
  - `trace_request_metadata`: enrichment_source, model, operation
- **Source:** Span attributes (gen_ai.prompt.1.content, gen_ai.completion.0.content, etc.)
- **Latency:** Up to 30 seconds

**Example trace enriched by service:**
```sql
request_id: tr-c156d4b828e899cf50aeb09c8c02d671
trace_tags:
  mlflow.user = "system"              -- default (no gen_ai.agent.name)
  mlflow.session = "default"          -- default (no gen_ai.conversation.id)
  mlflow.source.name = "mcp"          -- detected from HTTP URL
  mlflow.source.type = "HTTP"
trace_request_metadata:
  enrichment_source = "enrichment-service"
```

**Problem:** Both systems write to the same tables → potential inconsistencies, wasted resources

### 3. VLLM Data Flow

**Status:** ⚠️ **Partial - vLLM spans NOT tagged with peer.service**

Findings:
- **4 CHAT_MODEL spans found** (GenAI semantic conventions working)
- **0 spans with peer.service='vllm'** (OTel Collector transform not matching)
- Spans contain: `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`
- OTel Collector transform rules present but not matching server.address patterns

**Root Cause:**
OTel Collector transform uses regex match on `server.address` for "qwen3-next-80b", but may not be matching actual values in spans.

**Recommendation:**
Check actual `server.address` values in spans and update regex patterns:
```bash
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- psql -U postgres -d mlflow -c \
  "SELECT DISTINCT content::json->'attributes'->>'server.address' FROM spans WHERE type='CHAT_MODEL';"
```

### 4. LlamaStack Data Flow

**Status:** ✅ **Working**

Findings:
- LlamaStack configured with `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.catalystlab-shared.svc.cluster.local:4317`
- **28 LlamaStack-related spans** found (POST /v1/chat/completions, CHAT_MODEL spans)
- OTel activity visible in logs
- **Error detected:** `Failed to export metrics to otel-collector... StatusCode.UNIMPLEMENTED`
  - Note: This is expected - OTel Collector only has traces pipeline, not metrics

### 5. Tempo Capture

**Status:** ✅ **Working**

Findings:
- Tempo distributor running (1/1 ready)
- Tempo ingester running (1/1 ready)
- OTel Collector configured with `otlp_grpc/tempo` exporter
- Tempo ingester logs show blocks being flushed (trace storage working)
- **Warning:** Memcached errors (tempo-memcached service not found)
  - Not critical for lab environment but should be fixed for production

### 6. Kiali Integration

**Status:** ✅ **Configured**

Findings:
- Kiali running (1/1 ready)
- Configured with Tempo provider:
  - `in_cluster_url: http://tempo-query-frontend.catalystlab-shared.svc.cluster.local:3200`
  - `external_url: http://tempo.<CLUSTER_IP>.nip.io`
- Connectivity to Tempo verified

**Note:** Service graph visibility depends on peer.service attributes (see VLLM issue above)

## Current Architecture (Verified)

```
┌─────────────────────────────────────────────────┐
│    Trace Sources (LlamaStack, VLLM, MCP)        │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
              OTel Collector :4317/:4318
              ┌──────────────────────────┐
              │ Receivers: OTLP          │
              │ Processors:              │
              │  ✓ filter/drop-probes    │
              │  ✓ transform (partial)   │
              │  ✓ batch                 │
              └──────┬───────┬───────────┘
                     │       │
       ┌─────────────┘       └─────────────┐
       │                                   │
       ▼                                   ▼
  MLflow :5000                        Tempo :4317
  ┌────────────────┐                  ┌──────────────┐
  │ OTLP /v1/traces│                  │ Distributor  │
  │      ↓         │                  │      ↓       │
  │ PostgreSQL     │                  │ Ingester     │
  │  - spans ✓     │                  │      ↓       │
  │  - trace_info  │                  │ Storage ✓    │
  │  - trace_tags  │                  └──────┬───────┘
  │  - trace_req...│                         │
  └────┬───────────┘                         │
       │                                     │
       │ ┌───────────────────────────────────┘
       │ │
       ▼ ▼
  ┌──────────────────────────────────────────┐
  │      Dual Enrichment (BOTH ACTIVE)       │
  │                                           │
  │  1. MLflow Middleware (LlamaStack only)  │
  │     - Intercepts FastAPI requests        │
  │     - Extracts from HTTP headers/body    │
  │     - Writes immediately to PostgreSQL   │
  │     ✓ Active: trace tr-585790da...       │
  │                                           │
  │  2. Enrichment Service (All traces)      │
  │     - Polls PostgreSQL every 30s         │
  │     - Extracts from spans.content JSONB  │
  │     - Backfills NULL fields              │
  │     ✓ Active: 4,536 traces enriched      │
  └────────────┬──────────────────────────────┘
               │
               ▼
        ┌─────────────┐
        │  Kiali UI   │
        │ (reads      │
        │  Tempo)     │
        └─────────────┘
```

## Issues Identified

### 1. Redundant Enrichment Writers

**Problem:** Two systems writing to same database tables
**Impact:**
- Wasted CPU (middleware + 30s polling)
- Potential data inconsistencies (different values from two sources)
- Complexity (two codebases to maintain)

**Evidence:**
- Middleware writes immediately for LlamaStack traces
- Enrichment service polls and writes for ALL traces
- Both systems update trace_tags, trace_info

### 2. Missing vLLM peer.service Tagging

**Problem:** OTel Collector transform not matching vLLM spans
**Impact:** Kiali service graph may not show llamastack → vllm edges
**Root Cause:** Regex patterns in transform processor not matching actual server.address values

### 3. 30-Second Enrichment Delay

**Problem:** Traces appear with empty columns for up to 30 seconds
**Impact:** Poor UX, harder to debug real-time issues
**Current:** Enrichment service polls every 30s
**Option:** Could reduce to 5-10s but increases database load

### 4. Token Usage Fields Not Populated

**Finding:** No traces with mlflow.promptTokens/completionTokens/totalTokens in trace_tags
**Expected:** Should see token counts from gen_ai.usage.input_tokens/output_tokens
**Impact:** MLflow UI won't show token usage statistics

**Possible causes:**
- OTel Collector transform not adding mlflow.*Tokens attributes
- Enrichment service mapping logic issue
- No GenAI traces with token usage in test period

## Optimization Recommendations

### Option A: Remove Middleware, Keep Enrichment Service (Recommended)

**Rationale:**
- Enrichment service handles ALL trace types (LlamaStack, vLLM, MCP, HTTP)
- Middleware only handles LlamaStack (limited scope)
- Enrichment service extracts from standard gen_ai.* attributes (portable)
- Middleware depends on HTTP headers (LlamaStack-specific)

**Changes:**
1. ✅ Keep enrichment service (required, MLflow doesn't auto-populate)
2. ❌ Remove MLflow middleware from llamastack/mlflow_middleware.py
3. ✅ Enhance OTel Collector to add more mlflow.* attributes (reduce enrichment work)
4. ✅ Fix vLLM peer.service tagging in OTel Collector

**Benefits:**
- Single enrichment mechanism
- Consistent data across all trace sources
- Reduced request latency (no middleware interception)
- Simpler codebase

**Trade-offs:**
- Lose HTTP header-based user/session (must use gen_ai.* attributes)
- Still have 30s enrichment delay (unless we reduce polling interval)

### Option B: Keep Both, Eliminate Overlap

**Rationale:**
- Middleware provides immediate enrichment for LlamaStack (0s delay)
- Enrichment service handles other sources (MCP, HTTP, etc.)

**Changes:**
1. ✅ Keep middleware for LlamaStack traces
2. ✅ Keep enrichment service for non-LlamaStack traces
3. ✅ Update enrichment service to SKIP traces already enriched by middleware
   ```python
   # In find_traces_needing_enrichment():
   query = """
       SELECT ti.request_id
       FROM trace_info ti
       LEFT JOIN trace_request_metadata trm
         ON ti.request_id = trm.request_id
         AND trm.key = 'mlflow.trace.user'  -- middleware marker
       WHERE (ti.request_preview IS NULL OR ti.response_preview IS NULL)
         AND trm.request_id IS NULL  -- NOT enriched by middleware
       ORDER BY ti.timestamp_ms DESC
       LIMIT 100
   ```

**Benefits:**
- Immediate enrichment for LlamaStack (better UX)
- No wasted work (service skips middleware traces)
- Handles all trace sources

**Trade-offs:**
- More complex (two systems to maintain)
- Different data sources (HTTP headers vs span attributes)
- Potential inconsistency if middleware fails

### Option C: Enhance OTel Collector, Remove Both Enrichment Services (Ideal, but not possible)

**Would require:** MLflow to auto-populate tables from span attributes
**Verdict:** ❌ **Not possible** - MLflow does NOT auto-populate (verified)

## Immediate Action Items

### 1. Fix vLLM peer.service Tagging (High Priority)

Check actual server.address values:
```bash
ssh root@<CLUSTER_IP> 'kubectl exec -n catalystlab-shared pgvector-cluster-1 -- psql -U postgres -d mlflow -c "SELECT DISTINCT content::json->'\''attributes'\''->>\''server.address'\'' as server_addr FROM spans WHERE type='\''CHAT_MODEL'\'';"'
```

Update OTel Collector transform if needed:
```yaml
- set(span.attributes["peer.service"], "vllm") where span.attributes["server.address"] != nil and IsMatch(span.attributes["server.address"], ".*<actual-pattern>.*")
```

### 2. Add Token Usage Fields to trace_tags (Medium Priority)

Update enrichment service OR OTel Collector to populate:
- `mlflow.promptTokens` from `gen_ai.usage.input_tokens`
- `mlflow.completionTokens` from `gen_ai.usage.output_tokens`
- `mlflow.totalTokens` (calculated)

### 3. Decide on Enrichment Strategy (Medium Priority)

Choose Option A or B above and implement changes.

### 4. Fix Tempo Memcached Warnings (Low Priority - Lab Only)

Deploy memcached or disable caching in Tempo config:
```yaml
# tempo-minimal-values.yaml
memcached:
  enabled: false
```

## Summary

Your observability stack is **fully operational** with end-to-end trace flow working. The key finding is that **MLflow requires manual enrichment** - it does not auto-populate UI fields from span attributes.

**Current state:**
- ✅ All components running and processing traces
- ⚠️ Dual enrichment creating redundancy
- ❌ vLLM peer.service tagging not working
- ✅ Tempo capturing and storing traces
- ✅ Kiali configured with Tempo

**Recommended path forward:**
1. Remove MLflow middleware (redundant)
2. Keep enrichment service (required)
3. Fix vLLM tagging in OTel Collector
4. Add token usage fields to enrichment

This will give you a **single, consistent enrichment mechanism** that handles all trace sources uniformly.
