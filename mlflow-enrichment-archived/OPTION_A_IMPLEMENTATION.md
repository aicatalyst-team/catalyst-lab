# Option A Implementation Guide: Simplified Architecture

## Summary

Remove redundant MLflow middleware and rely solely on the enrichment service for trace metadata population. This creates a **single, consistent enrichment mechanism** that handles all trace sources uniformly.

## Status

✅ **vLLM peer.service tagging** - Already working (4 spans found with peer.service="vllm")
✅ **Enrichment service enhancement** - Code updated to extract version from model name
📝 **LlamaStack middleware removal** - Containerfile created, awaiting rebuild/deployment

## Changes Made

### 1. Enhanced Enrichment Service ✅

**File:** [mlflow/enrichment-service.py](mlflow/enrichment-service.py)
**File:** [mlflow/enrichment-deployment.yaml](mlflow/enrichment-deployment.yaml)

**Changes:**
- Extract version from model name (e.g., `RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8` → `Qwen3-Next-80B-A3B-Instruct-FP8`)
- Add both `mlflow.version` and `version` tags (for backward compatibility)
- Existing token usage logic confirmed working (mlflow.promptTokens, mlflow.completionTokens, mlflow.totalTokens)

**Code added:**
```python
# MLflow Version - extract from model name if available
version_value = 'v1.0'  # default
if attributes.get('model_name') and '/' in attributes['model_name']:
    # Extract version from model name
    version_value = attributes['model_name'].split('/')[-1]

tags.append({
    'key': 'mlflow.version',
    'value': version_value
})
# Also add version without mlflow prefix (for backward compatibility)
tags.append({
    'key': 'version',
    'value': version_value
})
```

### 2. LlamaStack Without Middleware ✅

**File:** [llamastack/Containerfile.no-middleware](llamastack/Containerfile.no-middleware)

New Containerfile created that removes MLflow middleware injection. Uses upstream llamastack image directly with only OpenTelemetry instrumentation.

## Deployment Steps

### Step 1: Apply Enhanced Enrichment Service

```bash
# Update the enrichment service ConfigMap
kubectl apply -f mlflow/enrichment-deployment.yaml

# Restart the enrichment service to load new code
kubectl rollout restart deployment/mlflow-enrichment -n catalystlab-shared

# Verify new version is running
kubectl logs -n catalystlab-shared deployment/mlflow-enrichment --tail=20
```

**Expected output:**
```
INFO - Starting MLflow Trace Enrichment Service
INFO - Configuration: poll_interval=30s, max_retries=10, retry_delay=0.5s
INFO - Connected to PostgreSQL at pgvector-cluster-rw.catalystlab-shared.svc.cluster.local:5432
INFO - Entering main processing loop
```

### Step 2: Rebuild LlamaStack Container (WITHOUT Middleware)

```bash
# From the llamastack directory
cd llamastack

# Build new container image
podman build -f Containerfile.no-middleware -t quay.io/rh-ee-gtrotman/llamastack-starter:no-middleware .

# Push to registry
podman push quay.io/rh-ee-gtrotman/llamastack-starter:no-middleware
```

### Step 3: Update LlamaStack Deployment

```bash
# Update the image in the deployment
kubectl set image deployment/llamastack -n catalystlab-shared \
  llamastack=quay.io/rh-ee-gtrotman/llamastack-starter:no-middleware

# Monitor rollout
kubectl rollout status deployment/llamastack -n catalystlab-shared

# Verify pod is running
kubectl get pods -n catalystlab-shared -l app=llamastack
```

### Step 4: Verify End-to-End Flow

```bash
# Generate a test trace
curl -X POST http://llamastack.<CLUSTER_IP>.nip.io/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "vllm/RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8",  # pragma: allowlist secret
    "messages": [{"role": "user", "content": "Test trace enrichment"}],
    "max_tokens": 10
  }'

# Wait 35 seconds for enrichment service to process
sleep 35

# Check database for enriched trace
ssh root@<CLUSTER_IP> 'kubectl exec -n catalystlab-shared pgvector-cluster-1 -- psql -U postgres -d mlflow -c "SELECT key, value FROM trace_tags WHERE request_id IN (SELECT trace_id FROM spans ORDER BY start_time_unix_nano DESC LIMIT 1) ORDER BY key;"'
```

**Expected output:**
```
            key             |                     value
----------------------------+-----------------------------------------------
 mlflow.session             | default
 mlflow.source.name         | llamastack
 mlflow.source.type         | GENAI
 mlflow.traceName           | chat RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8
 mlflow.user                | system
 mlflow.version             | Qwen3-Next-80B-A3B-Instruct-FP8
 version                    | Qwen3-Next-80B-A3B-Instruct-FP8
```

### Step 5: Verify Token Usage Fields

```bash
# Trigger another trace and check token fields
ssh root@<CLUSTER_IP> 'kubectl exec -n catalystlab-shared pgvector-cluster-1 -- psql -U postgres -d mlflow -c "SELECT key, value FROM trace_tags WHERE key LIKE '\''%Token%'\'' ORDER BY key LIMIT 10;"'
```

**Expected output:**
```
         key          | value
----------------------+-------
 mlflow.completionTokens | 153
 mlflow.promptTokens     | 63
 mlflow.totalTokens      | 216
```

## Verification Checklist

After deployment, verify:

- [ ] Enrichment service is running with new code
- [ ] LlamaStack pod restarted with new image (no middleware)
- [ ] New traces have `version` field extracted from model name
- [ ] Token usage fields populated (mlflow.promptTokens, mlflow.completionTokens, mlflow.totalTokens)
- [ ] No duplicate enrichment (check for absence of mlflow.trace.* in trace_request_metadata)
- [ ] MLflow UI shows all fields populated
- [ ] Tempo receiving traces from OTel Collector
- [ ] Kiali showing service graph with llamastack → vllm edges

## Rollback Plan

If issues occur, rollback to previous state:

```bash
# Rollback LlamaStack to previous image
kubectl set image deployment/llamastack -n catalystlab-shared \
  llamastack=quay.io/rh-ee-gtrotman/llamastack-starter:mlflow-minimal

# Rollback enrichment service
kubectl rollout undo deployment/mlflow-enrichment -n catalystlab-shared
```

## Expected Benefits

### Performance
- **Reduced latency:** No middleware interception on requests
- **Consistent enrichment delay:** All traces enriched within 30s (not immediate + delayed mix)

### Maintainability
- **Single enrichment point:** Only enrichment service to maintain
- **No container customization:** LlamaStack uses upstream image + OTel
- **Consistent data:** All traces enriched using same logic

### Data Quality
- **No duplicates:** Single writer to trace_tags/trace_info
- **Portable:** Works for ALL trace sources (LlamaStack, vLLM, MCP, HTTP, Kagent)
- **Standard attributes:** Uses gen_ai.* semantic conventions

## What Gets Removed

1. **llamastack/mlflow_middleware.py** - No longer needed
2. **Containerfile.minimal** - Replaced by Containerfile.no-middleware
3. **Custom image with middleware** - Use upstream or minimal customization
4. **trace_request_metadata mlflow.trace.*** - No longer written by middleware

## What Stays

1. **Enrichment service** - Primary enrichment mechanism
2. **OTel Collector transform** - Adds mlflow.spanType, peer.service, session.id, user.id
3. **MLflow OTLP ingestion** - Receives traces from OTel Collector
4. **Tempo** - Receives same traces for Grafana/Kiali
5. **Kiali integration** - Service graph visualization

## Architecture After Implementation

```
┌─────────────────────────────────────────────────┐
│    Trace Sources (LlamaStack, VLLM, MCP)        │
│    (OpenTelemetry auto-instrumentation)         │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
              OTel Collector :4317/:4318
              ┌──────────────────────────┐
              │ Receivers: OTLP          │
              │ Processors:              │
              │  ✓ filter/drop-probes    │
              │  ✓ transform             │
              │    - mlflow.spanType     │
              │    - peer.service=vllm   │
              │    - session.id          │
              │    - user.id             │
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
       ▼                                     ▼
  ┌──────────────────────────────┐   ┌─────────────┐
  │  Enrichment Service (ONLY)   │   │  Kiali UI   │
  │                              │   │ (reads      │
  │  - Polls every 30s           │   │  Tempo)     │
  │  - Extracts from gen_ai.*    │   └─────────────┘
  │  - Backfills ALL fields:     │
  │    ✓ trace_tags              │
  │    ✓ trace_info              │
  │    ✓ trace_request_metadata  │
  │  - Source: gen_ai.*, http.*  │
  │  - Version: from model name  │
  │  - Tokens: input/output/tot  │
  └──────────────────────────────┘
```

**Key change:** Single enrichment path (enrichment service) instead of dual (middleware + service).

## Troubleshooting

### Issue: Traces not being enriched

**Check:**
```bash
kubectl logs -n catalystlab-shared deployment/mlflow-enrichment --tail=50
```

**Expected:** Should see "Found X traces needing enrichment" every 30s

**Fix:** Restart enrichment service

### Issue: Version field still showing "v1.0"

**Check:**
```bash
# Verify enrichment service code has new logic
kubectl get configmap mlflow-enrichment-script -n catalystlab-shared -o yaml | grep -A 5 "version_value"
```

**Fix:** Re-apply enrichment-deployment.yaml

### Issue: Token fields not populated

**Check:**
```bash
# Verify spans have gen_ai.usage.* attributes
ssh root@<CLUSTER_IP> "kubectl exec -n catalystlab-shared pgvector-cluster-1 -- psql -U postgres -d mlflow -c \"SELECT content::json->'attributes'->>'gen_ai.usage.input_tokens' FROM spans WHERE type='CHAT_MODEL' LIMIT 1;\""
```

**Expected:** Should return a number

**Fix:** If NULL, check OpenTelemetry instrumentation on LlamaStack

### Issue: Middleware still running

**Check:**
```bash
# Check which image is running
kubectl get deployment llamastack -n catalystlab-shared -o jsonpath='{.spec.template.spec.containers[0].image}'
```

**Expected:** Should be `quay.io/rh-ee-gtrotman/llamastack-starter:no-middleware`

**Fix:** Re-run Step 3 (update deployment)

## Next Steps

After successful implementation:

1. Monitor for 24 hours to ensure all traces are enriched correctly
2. Update documentation to reflect new architecture
3. Remove old mlflow_middleware.py file from repository
4. Archive Containerfile.minimal (keep for reference but don't use)
5. Update CLAUDE.md if needed

## Success Criteria

✅ All new traces enriched by service within 30 seconds
✅ No mlflow.trace.* entries in trace_request_metadata (middleware removed)
✅ Version field extracted from model name
✅ Token usage fields populated
✅ No duplicate enrichment
✅ MLflow UI shows complete metadata
✅ Kiali service graph shows llamastack → vllm edges
