# MLflow — Trace Visualization & Experiment Tracking

Deployed in `catalystlab-shared` alongside PostgreSQL and LLaMA Stack.

## Live State (discovered 2026-02-23)

| Property | Value |
|----------|-------|
| Namespace | `catalystlab-shared` |
| Image | `ghcr.io/mlflow/mlflow:latest-full` |
| External URL | `http://mlflow.<CLUSTER-IP>.nip.io` |
| Internal URL | `mlflow.catalystlab-shared.svc.cluster.local:5000` |
| Backend store | PostgreSQL `mlflow` database on `pgvector-cluster-rw` |
| Artifact store | PVC `/mlflow/artifacts` (10Gi, `local-path`) |
| OTel Collector | `otel-collector.catalystlab-shared.svc.cluster.local:4317` (gRPC) / `:4318` (HTTP) |
| Experiment | `llamastack-traces` — ID **1** (already created) |

### Experiments

| ID | Name | Kind | Status |
|----|------|------|--------|
| 0 | Default | — | Active |
| 1 | `llamastack-traces` | `genai_development` | Active, receiving traces |

### Traces (as of 2026-02-23)

- **35,033 traces** / **105,099 spans** in experiment `1`
- All current traces are `GET /v1/models` — readiness/liveness probe noise from LLaMA Stack auto-instrumentation
- Real inference traces will appear when `/v1/chat/completions` is called against LLaMA Stack

## Architecture

```
LLaMA Stack :8321
  └─(OTel SDK, auto-instruments ALL HTTP)──► otel-collector :4317
                                                 └─(otlphttp /v1/traces)──► MLflow :5000
                                                                                └── PostgreSQL (mlflow db)
                                                                                └── PVC (artifacts)
```

The OTel Collector receives on gRPC `:4317` and HTTP `:4318`, exports via `otlphttp` to MLflow's OTLP ingestion endpoint with the `x-mlflow-experiment-id: "1"` header.

## Deployment Manifests

### MLflow Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mlflow
  namespace: catalystlab-shared
  labels:
    app: mlflow
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mlflow
  template:
    metadata:
      labels:
        app: mlflow
    spec:
      containers:
        - name: mlflow
          image: ghcr.io/mlflow/mlflow:latest-full
          command:
            - mlflow
            - server
            - --host=0.0.0.0
            - --port=5000
            - --backend-store-uri=postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@pgvector-cluster-rw:5432/mlflow
            - --artifacts-destination=/mlflow/artifacts
            - --allowed-hosts=mlflow.<CLUSTER-IP>.nip.io,mlflow.catalystlab-shared.svc.cluster.local,mlflow.catalystlab-shared.svc.cluster.local:5000,localhost,localhost:5000
          ports:
            - containerPort: 5000
          env:
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: pgvector-cluster-app
                  key: username
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: pgvector-cluster-app
                  key: password
            - name: MLFLOW_TRACKING_URI
              value: "postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@pgvector-cluster-rw:5432/mlflow"
          volumeMounts:
            - name: artifacts
              mountPath: /mlflow/artifacts
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: "2"
              memory: 2Gi
          readinessProbe:
            httpGet:
              path: /health
              port: 5000
            initialDelaySeconds: 10
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /health
              port: 5000
            initialDelaySeconds: 20
            periodSeconds: 30
      volumes:
        - name: artifacts
          persistentVolumeClaim:
            claimName: mlflow-artifacts-pvc
```

### PVC

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mlflow-artifacts-pvc
  namespace: catalystlab-shared
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: local-path
  resources:
    requests:
      storage: 10Gi
```

### Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: mlflow
  namespace: catalystlab-shared
spec:
  selector:
    app: mlflow
  ports:
    - port: 5000
      targetPort: 5000
```

### Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mlflow
  namespace: catalystlab-shared
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "0"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
spec:
  ingressClassName: nginx
  rules:
    - host: mlflow.<CLUSTER-IP>.nip.io
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: mlflow
                port:
                  number: 5000
```

### OTel Collector ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: otel-collector-config
  namespace: catalystlab-shared
data:
  config.yaml: |
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: "0.0.0.0:4317"
          http:
            endpoint: "0.0.0.0:4318"

    exporters:
      otlphttp:
        endpoint: "http://mlflow.catalystlab-shared.svc.cluster.local:5000"
        headers:
          x-mlflow-experiment-id: "1"

    service:
      pipelines:
        traces:
          receivers: [otlp]
          exporters: [otlphttp]
```

> **Note:** `otlphttp` alias is deprecated in otel-collector-contrib 0.146.1+. Use `otlp_http` when upgrading. The alias still works but produces a warning at startup.

### OTel Collector Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: otel-collector
  namespace: catalystlab-shared
spec:
  replicas: 1
  selector:
    matchLabels:
      app: otel-collector
  template:
    metadata:
      labels:
        app: otel-collector
    spec:
      containers:
        - name: otel-collector
          image: otel/opentelemetry-collector-contrib:latest
          args: ["--config=/etc/otel/config.yaml"]
          ports:
            - containerPort: 4317
              name: grpc
            - containerPort: 4318
              name: http
          volumeMounts:
            - name: config
              mountPath: /etc/otel
          resources:
            requests:
              cpu: 200m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 512Mi
      volumes:
        - name: config
          configMap:
            name: otel-collector-config
---
apiVersion: v1
kind: Service
metadata:
  name: otel-collector
  namespace: catalystlab-shared
spec:
  selector:
    app: otel-collector
  ports:
    - name: grpc
      port: 4317
      targetPort: 4317
    - name: http
      port: 4318
      targetPort: 4318
```

## Trace Visualization in the MLflow UI

Navigate to `http://mlflow.<CLUSTER-IP>.nip.io`:

1. Select **Experiments → llamastack-traces**
2. Click the **Traces** tab (distinct from Runs)
3. Each row is one trace — click to open the span tree view

**Span tree layout** (what you'll see for real inference traces):
```
inference-request (root, e.g. POST /v1/chat/completions)
├── llm-call
│   ├── model: RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8
│   ├── llm.token_count.prompt
│   ├── llm.token_count.completion
│   └── llm.latency_ms
└── (tool calls, agent steps — when agents are added)
```

The timeline view shows a waterfall chart of parallel/sequential spans. Span attributes (model name, token counts, custom tags) are visible in the detail panel.

**Current state of traces:** All existing traces are `GET /v1/models` health probe noise — 3 spans each (root + 2 http send children), ~2ms duration, every 10-30s. Real inference spans will appear once someone calls `/v1/chat/completions` on LLaMA Stack.

## Known Caveats

### 1. `--allowed-hosts` must include port variants

MLflow 3.x uses `fnmatch`-based DNS rebinding protection that does **not** strip ports from the `Host` header. Both forms must be listed:

```
--allowed-hosts=mlflow.<CLUSTER-IP>.nip.io,\
  mlflow.catalystlab-shared.svc.cluster.local,\
  mlflow.catalystlab-shared.svc.cluster.local:5000,\
  localhost,localhost:5000
```

`/health` is exempt from host validation — it will always return 200. Use the experiments API to test for real:
```bash
curl -X POST http://mlflow.<CLUSTER-IP>.nip.io/api/2.0/mlflow/experiments/search \
  -H 'Content-Type: application/json' -d '{"max_results": 10}'
```

### 2. `MLFLOW_TRACKING_URI` env var is required

MLflow 3.x has a store initialization bug: FastAPI gateway workers resolve the tracking store from the `MLFLOW_TRACKING_URI` **environment variable**, not from `--backend-store-uri`. If this env var is missing, Gateway API routes will fail even though the tracking server works. Always set both.

### 3. OTel endpoint: `/v1/traces` not `/api/2.0/mlflow/traces`

| Path | Purpose |
|------|---------|
| `/v1/traces` | **OTLP ingestion** — protobuf, used by OTel Collector (`otlphttp` exporter) |
| `/api/2.0/mlflow/traces` | REST API for querying trace records — JSON, not OTLP |

The `otlphttp` exporter automatically appends `/v1/traces` to the configured `endpoint`. Set `endpoint` to the base URL (`http://mlflow…:5000`), not the full path.

### 4. No openinference filter in the OTel Collector

Do NOT add openinference semantic convention filters. LLaMA Stack emits standard OTel spans — filtering on openinference conventions silently drops everything.

### 5. Health probe noise

LLaMA Stack auto-instruments all HTTP traffic including its own readiness/liveness probes (`GET /v1/models` every 10-30s). The `llamastack-traces` experiment will accumulate thousands of 2ms probe traces. Options to address:
- Add a filter processor in the OTel collector to drop spans where `http.route = "/v1/models"` and `http.method = "GET"`
- Create a separate experiment for probe traffic and route by span name
- Pin the MLflow LLaMA Stack's k8s probes to a separate non-instrumented path (if available)

### 6. `x-mlflow-experiment-id` bootstrap sequence

The OTel collector needs the numeric experiment ID before traces can be routed. The sequence is:

```bash
# 1. Deploy MLflow
# 2. Create experiment
curl -X POST http://mlflow.<CLUSTER-IP>.nip.io/api/2.0/mlflow/experiments/create \
  -H 'Content-Type: application/json' -d '{"name": "my-experiment"}'
# Returns: {"experiment_id": "2"}

# 3. Update otel-collector-config ConfigMap with the new ID
# 4. kubectl rollout restart deployment/otel-collector -n catalystlab-shared
```

For our stack, experiment `llamastack-traces` (ID=`1`) is already created and the collector is already configured. If you add new experiments, you'll need to update the ConfigMap or add a second exporter pipeline for that experiment.

### 7. `otlphttp` exporter alias deprecation

`otel-collector-contrib` 0.146.1 logs a warning at startup:
```
"otlphttp" alias is deprecated; use "otlp_http" instead
```
The exporter still works. Rename to `otlp_http` when updating the ConfigMap.

### 8. AI Gateway requires `/v1` in `api_base`

The MLflow built-in AI Gateway (REST API at `/api/3.0/mlflow/gateway/`) proxies inference to upstream endpoints. When creating a gateway secret, `auth_config.api_base` must include the `/v1` suffix — the OpenAI provider passes it directly to the SDK without appending any path.

## Adding a New Benchmark Experiment

For each new benchmark run (GuideLLM, Vending-Bench, etc.) create a separate experiment:

```bash
curl -X POST http://mlflow.<CLUSTER-IP>.nip.io/api/2.0/mlflow/experiments/create \
  -H 'Content-Type: application/json' \
  -d '{"name": "guidellm-sweep-2026-02-23", "tags": [{"key": "mlflow.experimentKind", "value": "genai_development"}]}'
```

Then either:
- Update the OTel collector ConfigMap to route traces to the new experiment ID, or
- Log GuideLLM metrics directly via the REST API: `POST /api/2.0/mlflow/runs/create` + `POST /api/2.0/mlflow/runs/log-metric`

## Verification

```bash
# Health (always 200 — not a real test)
curl http://mlflow.<CLUSTER-IP>.nip.io/health

# Real API test (403 = --allowed-hosts misconfiguration)
curl -X POST http://mlflow.<CLUSTER-IP>.nip.io/api/2.0/mlflow/experiments/search \
  -H 'Content-Type: application/json' -d '{"max_results": 10}'

# Count traces in experiment 1
curl -s "http://mlflow.<CLUSTER-IP>.nip.io/api/2.0/mlflow/traces" \
  -G --data-urlencode "experiment_ids=1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('traces',[])))"

# Span breakdown from PostgreSQL
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U postgres -d mlflow -c \
  "SELECT name, count(*) FROM spans GROUP BY name ORDER BY count(*) DESC LIMIT 10;"

# OTel collector logs (no errors = healthy)
kubectl logs -n catalystlab-shared -l app=otel-collector --tail=5
```

## Connections Summary

| Component | Connects to MLflow via | Purpose |
|-----------|----------------------|---------|
| OTel Collector | `otlphttp` → `:5000/v1/traces` | Trace ingestion from LLaMA Stack |
| PostgreSQL | `postgresql://` backend-store | Metadata, runs, traces, spans |
| PVC | Filesystem mount | Artifact storage |
| nginx ingress | HTTP → `:5000` | External UI + API access |

## PostgreSQL Schema (MLflow tables)

42 tables in `mlflow` database. Key tables for observability:

| Table | Purpose |
|-------|---------|
| `trace_info` | One row per trace (request_id, timestamp, duration, status) |
| `spans` | One row per span (span_id, parent_span_id, name, type, content/attributes) |
| `trace_tags` | Tags attached to traces |
| `experiments` | Experiment registry |
| `runs` | Experiment run records |
| `metrics` / `latest_metrics` | Logged metrics per run |
| `params` | Run parameters |

The `spans.content` column stores span attributes as JSON.
