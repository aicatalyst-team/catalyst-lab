# OTel Collector — `catalystlab-shared`

Central trace pipeline for the shared lab stack. Receives OTLP traces from LLaMA Stack (auto-instrumented via `opentelemetry-distro` sitecustomize) and exports to MLflow + Jaeger.

## Architecture

```
LLaMA Stack (FastAPI + openai-v2 auto-instrumentation)
    │
    ▼ OTLP gRPC :4317 / HTTP :4318
OTel Collector (catalystlab-shared)
    │
    ├─ filter/drop-probes  → drops GET /v1/models (readiness/liveness probes)
    ├─ transform           → injects mlflow.spanType, sets peer.service for vLLM
    │
    ├──▶ MLflow  (otlphttp → :5000, experiment ID 1)
    └──▶ Jaeger  (otlp/jaeger → :4317)
```

## Deployment

```bash
kubectl apply -f otel-collector.yaml
kubectl rollout restart deployment/otel-collector -n catalystlab-shared
```

## Key Processors

### `filter/drop-probes`
Drops readiness/liveness probe spans (`GET /v1/models`). Without this, probe traces outnumber real inference traces ~150:1.

### `transform`
OTTL statements that enrich spans:

| Statement | Purpose |
|-----------|---------|
| `mlflow.spanType = "CHAT_MODEL"` | Populates MLflow's "Span Type" column for chat inference spans |
| `mlflow.spanType = "LLM"` | Same for text completion spans |
| `service.name = "vllm"` | Creates vLLM service node in Jaeger's dependency graph |
| `peer.service = "vllm"` | Enables Jaeger's trace graph view for llamastack → vllm calls |

## Known Limitations

### Request/Response Preview in MLflow (Empty)

MLflow's `request_preview` / `response_preview` columns require `mlflow.spanInputs` / `mlflow.spanOutputs` span attributes. These are NOT set by `opentelemetry-instrumentation-openai-v2` v2.3b0.

**Root cause:** The openai-v2 instrumentation emits prompt/response content via OTel **EventLogger** (log records), not as span attributes or span events. MLflow does not accept OTLP logs (`/v1/logs` returns 404). Cross-signal log-to-span merging is not possible in the OTel Collector (OTTL does not support cross-signal operations).

**Path forward:**
1. **Short-term (Jaeger):** Content inspection via Jaeger once a LoggerProvider is configured in LLaMA Stack. `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` is already set — it just needs a LoggerProvider to export the log records.
2. **Medium-term (upstream fix):** `opentelemetry-util-genai` already has `ContentCapturingMode.SPAN_AND_EVENT` which places content on BOTH span attributes AND log events. When `openai-v2` adopts this mode, setting `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_AND_EVENT` will populate span attributes that MLflow can read — no collector changes needed.

### Deprecated Exporter Aliases

Collector v0.146.1 warns about deprecated aliases:
- `otlphttp` → should be `otlp_http`
- `otlp` → should be `otlp_grpc`

Both still work. Update when convenient.

## Caveats

- Image is `otel/opentelemetry-collector-contrib:latest` — consider pinning for reproducibility
- OTTL auto-corrects `attributes["..."]` to `span.attributes["..."]` — this is cosmetic, not an error
- The MLflow exporter uses experiment ID `1` (hardcoded header `x-mlflow-experiment-id: "1"`)
