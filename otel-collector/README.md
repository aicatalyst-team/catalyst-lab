# OTel Collector — `catalystlab-shared`

Central trace pipeline for the shared lab stack. Receives OTLP traces from LLaMA Stack (auto-instrumented via `opentelemetry-distro` sitecustomize) and exports to MLflow + Tempo.

## Architecture

```
LLaMA Stack (FastAPI + openai-v2 auto-instrumentation)
    │
    ▼ OTLP gRPC :4317 / HTTP :4318
OTel Collector (catalystlab-shared)
    │
    ├─ filter/drop-probes  → drops GET /v1/models (readiness/liveness probes)
    ├─ transform           → injects mlflow.spanType, sets peer.service for dependency graphs
    │
    ├──▶ MLflow  (otlp_http → :5000, experiment ID 1)
    ├──▶ Tempo   (otlp_grpc/tempo → :4317)
    ├──▶ spanmetrics connector   → duration histograms, call counters
    └──▶ servicegraph connector  → service-to-service edge metrics
         │
         └──▶ Prometheus (:8889) → scraped by ServiceMonitor
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
| `service.name = "vllm"` | Fixes vLLM's `unknown_service` to `vllm` for Tempo/Grafana service graphs |
| `peer.service = "vllm"` | Enables Tempo/Kiali service dependency edges for llamastack → vllm calls |
| `session.id` / `user.id` | Maps gen_ai attributes to MLflow session/user columns |

## Connectors

### `spanmetrics`
Generates per-service, per-span-name metrics from traces. Replaces Tempo's built-in metrics_generator (removed from cluster).

**Metrics produced**:
- `traces_spanmetrics_duration_milliseconds_{bucket,sum,count}` - Latency histograms
- `traces_spanmetrics_calls_total` - Request counters

**Dimensions**: `service.name`, `span.name`, `span.kind`, `status.code`, `peer.service`

### `servicegraph`
Generates service-to-service edge metrics from traces using `peer.service` attributes set by the transform processor.

**Metrics produced**:
- `traces_service_graph_request_total` - Request count between services
- `traces_service_graph_request_failed_total` - Failed requests
- `traces_service_graph_request_server_seconds_{bucket,sum,count}` - Latency between services

**Example**: llamastack → vllm edge appears in Grafana service graph dashboards.

**Prometheus Export**: All connector metrics exposed at `:8889/metrics` and scraped by the ServiceMonitor.

## Known Limitations

### Request/Response Preview in MLflow (RESOLVED)

**Issue:** MLflow's `request_preview` / `response_preview` columns require `mlflow.spanInputs` / `mlflow.spanOutputs` span attributes. These are NOT set by `opentelemetry-instrumentation-openai-v2` v2.3b0.

**Root cause:** The openai-v2 instrumentation emits prompt/response content via OTel **EventLogger** (log records), not as span attributes or span events. MLflow does not accept OTLP logs (`/v1/logs` returns 404). Cross-signal log-to-span merging is not possible in the OTel Collector (OTTL does not support cross-signal operations).

**Resolution:** Custom MLflow middleware in LLaMA Stack (`mlflow_middleware.py`) intercepts requests and writes metadata directly to PostgreSQL tables:
- `trace_tags` → User, Session, Trace Name, Version, Source (UI columns)
- `trace_info` → Request Preview, Response Preview (extracted from message content)
- `trace_request_metadata` → Additional metadata storage

This bypasses the OTel instrumentation limitations and populates all MLflow UI fields.

### Deprecated Exporter Aliases

Collector v0.146.1 warns about deprecated aliases:
- `otlphttp` → should be `otlp_http`
- `otlp` → should be `otlp_grpc`

Both still work. Update when convenient.

## Caveats

- Image is `otel/opentelemetry-collector-contrib:latest` — consider pinning for reproducibility
- OTTL auto-corrects `attributes["..."]` to `span.attributes["..."]` — this is cosmetic, not an error
- The MLflow exporter uses experiment ID `1` (hardcoded header `x-mlflow-experiment-id: "1"`)
