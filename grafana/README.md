# Grafana - Observability Visualization Platform

> 📝 **CONFIGURATION NOTE**: This README uses placeholders for environment-specific values. Grafana datasources are pre-configured via the prometheus-stack Helm chart. The Tempo datasource was added on March 17, 2026 to support distributed tracing visualization.

> 🔄 **TEMPO INTEGRATION**: Grafana now includes a Tempo datasource for distributed trace visualization, replacing the previous Jaeger integration. Tempo provides TraceQL query support, metrics generation, and native Grafana integration.

Grafana provides unified observability visualization for the AI Catalyst Lab, combining metrics from Prometheus, distributed traces from Tempo, and logs from Loki. It serves as the primary interface for monitoring LLM inference performance, service dependencies, and trace analysis.

**Target cluster:** `root@<CLUSTER_IP>`
**Namespace:** `monitoring`
**Installation:** Managed by `kube-prometheus-stack` Helm chart

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Data Sources                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Prometheus  │  │    Tempo     │  │  Alertmanager│          │
│  │   (metrics)  │  │   (traces)   │  │   (alerts)   │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
└─────────┼──────────────────┼──────────────────┼──────────────────┘
          │                  │                  │
          └──────────────────┴──────────────────┘
                             │
                    ┌────────▼────────┐
                    │     Grafana     │
                    │  (visualization) │
                    └────────┬────────┘
                             │
          ┌──────────────────┴──────────────────┐
          │                                     │
    ┌─────▼─────┐                      ┌───────▼───────┐
    │ Dashboards│                      │   Explore UI  │
    │ - Metrics │                      │ - TraceQL     │
    │ - Graphs  │                      │ - Trace View  │
    │ - Panels  │                      │ - Service Map │
    └───────────┘                      └───────────────┘
```

## Configured Datasources

### 1. Prometheus (Default)

**Type:** `prometheus`
**UID:** `prometheus`
**URL:** `http://prometheus-stack-kube-prom-prometheus.monitoring:9090/`

**Purpose:**
- Metrics from instrumented services
- OTel Collector span metrics (`traces_spanmetrics_*`)
- Service graph metrics (`traces_service_graph_*`)
- Pod/Node resource utilization

**Configuration:**
```yaml
datasources:
- name: Prometheus
  type: prometheus
  uid: prometheus
  url: http://prometheus-stack-kube-prom-prometheus.monitoring:9090/
  access: proxy
  isDefault: true
  jsonData:
    httpMethod: POST
    timeInterval: 30s
```

### 2. Tempo (Distributed Tracing)

**Type:** `tempo`
**UID:** `tempo`
**URL:** `http://tempo-query-frontend.catalystlab-shared:3200`

**Purpose:**
- Distributed trace visualization
- TraceQL query interface
- Service dependency mapping
- Trace-to-logs correlation (via Loki)

**Configuration:**
```yaml
- name: Tempo
  type: tempo
  uid: tempo
  url: http://tempo-query-frontend.catalystlab-shared:3200
  access: proxy
  jsonData:
    httpMethod: GET
    tracesToLogsV2:
      datasourceUid: loki
    serviceMap:
      datasourceUid: prometheus
    nodeGraph:
      enabled: true
```

**Features:**
- **TraceQL**: Advanced trace queries with `| rate()` aggregations
- **Metrics Generator**: Generates service graph and span metrics from traces
- **Node Graph**: Visualizes service dependencies from trace data
- **Traces-to-Logs**: Links traces to log entries (when Loki is configured)

### 3. Alertmanager

**Type:** `alertmanager`
**UID:** `alertmanager`
**URL:** `http://prometheus-stack-kube-prom-alertmanager.monitoring:9093/`

**Purpose:**
- Alert routing and notification
- Alert grouping and deduplication
- Integration with notification channels

## Dashboards

### AI Catalyst Lab Overview

**UID:** `catalyst-lab-overview`

10-panel dashboard providing unified view of the AI inference stack:

| # | Panel | Type | Data Source | Query |
|---|-------|------|-------------|-------|
| 1 | Service-to-Service Request Flow | Bar Gauge | Prometheus | `traces_service_graph_request_total` |
| 2 | Agent Request Rate | Time Series | Prometheus | `traces_service_graph_request_total` |
| 3 | LLM Inference Latency | Histogram | Prometheus | `traces_spanmetrics_duration_milliseconds_bucket` |
| 4 | Service Graph Request Rates | Bar Gauge | Prometheus | `traces_service_graph_request_total` |
| 5 | Active Agent Services | Stat | Prometheus | `traces_spanmetrics_calls_total` |
| 6 | Total LLM Calls | Stat | Prometheus | `traces_spanmetrics_calls_total` |
| 7 | Error Rate | Stat | Prometheus | `traces_service_graph_request_failed_total` |
| 8 | Service-to-Service Latency P50 | Table | Prometheus | `traces_service_graph_request_server_seconds_bucket` |
| 9 | Agent Span Counts by Operation | Stacked Bars | Prometheus | `traces_spanmetrics_calls_total` |
| 10 | Recent Traces | Table | Tempo | TraceQL search |

**Metrics Source:**
- Prometheus metrics are generated by **Tempo's metrics generator**
- Spans flow: llamastack/vLLM → OTel Collector → Tempo → Metrics Generator → Prometheus (via ServiceMonitor)

**Trace Source:**
- Panel 10 queries Tempo directly using TraceQL
- Click traces to drill down into full trace view with GenAI semantic conventions

### Planned Additions (Observability Cost Panels)

**Panel 11: OTel Spans Before/After Filtering**

Visualizes probe span filtering impact (108 spans/min dropped by `filter/drop-probes`):

```promql
# Total span rate (all spans reaching collector)
sum(rate(otelcol_receiver_accepted_spans[5m]))

# Dropped probe spans
sum(rate(otelcol_processor_dropped_spans{processor="filter/drop-probes"}[5m]))
```

**Panel 12: Signal-to-Noise Ratio**

Percentage of exported spans that are real user requests vs probes:

```promql
# Signal ratio = exported / received
sum(rate(otelcol_exporter_sent_spans[5m]))
/
sum(rate(otelcol_receiver_accepted_spans[5m]))
* 100
```

## Using Grafana

### Access

**Internal:** `http://prometheus-stack-grafana.monitoring.svc.cluster.local`
**External:** `http://<CLUSTER_IP>:3000` (via Ingress)

**Default credentials:**
- Username: `admin`
- Password: Stored in `prometheus-stack-grafana` secret

### Explore Traces (Tempo)

1. Navigate to **Explore** → Select **Tempo** datasource
2. Use **TraceQL** queries:
   ```traceql
   # Find all llamastack traces
   {resource.service.name="llamastack"}

   # Find chat completions with high latency
   {resource.service.name="llamastack" && name="POST /v1/chat/completions" && duration > 500ms}

   # Find traces with specific model
   {resource.gen_ai.request.model="RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8"}

   # Rate query (requires metrics generator)
   {resource.service.name="llamastack"} | rate() by(resource.service.name)
   ```

3. **Trace View Features:**
   - Span hierarchy with timing
   - GenAI semantic conventions (model, tokens, operation)
   - HTTP attributes (method, status, URL)
   - Database operations (SQL queries)
   - Service dependency visualization

### Service Map (Node Graph)

1. Navigate to **Explore** → **Tempo**
2. Query for traces: `{resource.service.name="llamastack"}`
3. Click **Node Graph** tab
4. View service dependencies:
   - llamastack → vLLM
   - Agents → llamastack
   - llamastack → PostgreSQL

## Tempo Metrics Generator

**Enabled:** March 17, 2026
**Configuration:** `/tmp/tempo-s3-values.yaml`

```yaml
metricsGenerator:
  enabled: true
  replicas: 1
  resources:
    limits:
      cpu: 200m
      memory: 256Mi
```

**What it generates:**

1. **Service Graph Metrics** (`traces_service_graph_*`):
   - `traces_service_graph_request_total` - Request count between services
   - `traces_service_graph_request_failed_total` - Failed requests
   - `traces_service_graph_request_server_seconds_bucket` - Latency histograms

2. **Span Metrics** (`traces_spanmetrics_*`):
   - `traces_spanmetrics_calls_total` - Span call counts by operation
   - `traces_spanmetrics_duration_milliseconds_bucket` - Latency distribution
   - `traces_spanmetrics_size_total` - Span size metrics

**ServiceMonitor:**
```yaml
serviceMonitor:
  enabled: true
  labels:
    release: prometheus-stack
```

Prometheus scrapes metrics from Tempo's metrics generator endpoint, making them available in Grafana dashboards.

## Trace Data Flow

```
llamastack (OpenTelemetry instrumented)
  ↓ OTLP gRPC (4317)
OTel Collector
  ├─ Processors: filter/drop-probes, transform, batch
  └─ Exporters:
      ├→ MLflow (experiment #1 "llamastack-traces")
      └→ Tempo Distributor
          ↓
      Tempo Ingester → S3 (MinIO)
          ↓
      Tempo Metrics Generator → Prometheus (ServiceMonitor)
          ↓
      Grafana Datasources:
          ├─ Prometheus (metrics, dashboards)
          └─ Tempo (traces, TraceQL, node graph)
```

## Verification

### Check Datasources

```bash
# Port-forward to Grafana
ssh root@<CLUSTER_IP> 'kubectl port-forward -n monitoring svc/prometheus-stack-grafana 3000:3000' &

# List datasources (requires API key or login)
curl -s http://admin:prom-operator@localhost:3000/api/datasources | jq '.[] | {name, type, url}'  # pragma: allowlist secret

# Expected output:
# {
#   "name": "Prometheus",
#   "type": "prometheus",
#   "url": "http://prometheus-stack-kube-prom-prometheus.monitoring:9090/"
# }
# {
#   "name": "Tempo",
#   "type": "tempo",
#   "url": "http://tempo-query-frontend.catalystlab-shared:3200"
# }
# {
#   "name": "Alertmanager",
#   "type": "alertmanager",
#   "url": "http://prometheus-stack-kube-prom-alertmanager.monitoring:9093/"
# }
```

### Test Tempo Datasource

```bash
# Query Tempo via Grafana proxy
curl -s http://admin:prom-operator@localhost:3000/api/datasources/proxy/tempo/api/search?limit=5 | jq '.traces[] | {traceID, rootServiceName, rootTraceName}'  # pragma: allowlist secret
```

### Verify Metrics Generator

```bash
# Check Tempo metrics generator pod
ssh root@<CLUSTER_IP> 'kubectl get pods -n catalystlab-shared -l app.kubernetes.io/component=metrics-generator'

# Verify Prometheus is scraping Tempo metrics
ssh root@<CLUSTER_IP> 'kubectl exec -n monitoring prometheus-stack-kube-prom-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=traces_service_graph_request_total" | jq .'
```

## Export / Import Dashboards

### Export from Live Grafana

```bash
# Port-forward to Grafana
kubectl port-forward -n monitoring svc/prometheus-stack-grafana 3000:3000 &

# Run export script
./scripts/export-grafana-dashboard.sh catalyst-lab-overview > grafana/catalyst-lab-overview.json
```

### Import Dashboard

```bash
GRAFANA_URL="http://<CLUSTER_IP>:3000"
GRAFANA_API_KEY="<API_KEY>"

curl -X POST "${GRAFANA_URL}/api/dashboards/db" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${GRAFANA_API_KEY}" \
  -d @grafana/catalyst-lab-overview.json
```

## Troubleshooting

### Issue: Tempo Datasource Shows "Data source connected, but no trace data found"

**Symptom:** Grafana connects to Tempo but queries return no traces.

**Causes:**
1. No traces in Tempo yet (new deployment)
2. OTel Collector not sending traces to Tempo
3. Time range doesn't match trace timestamps

**Solutions:**
```bash
# 1. Verify traces exist in Tempo
ssh root@<CLUSTER_IP> 'kubectl exec -n monitoring deploy/prometheus-stack-grafana -- \
  curl -s http://tempo-query-frontend.catalystlab-shared:3200/api/search?limit=10'

# 2. Check OTel Collector → Tempo export
ssh root@<CLUSTER_IP> 'kubectl logs -n catalystlab-shared deploy/otel-collector | grep tempo'

# 3. Generate test trace
ssh root@<CLUSTER_IP> 'kubectl exec -n catalystlab-shared deploy/llamastack -- \
  curl -s -X POST http://localhost:8321/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '"'"'{"model":"vllm/RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8","messages":[{"role":"user","content":"test"}],"max_tokens":5}'"'"''  # pragma: allowlist secret
```

### Issue: TraceQL Rate Queries Fail with "empty ring" Error

**Symptom:**
```
failed to execute TraceQL query: {resource.service.name="llamastack"} | rate()
Status: 500 Internal Server Error
Body: error querying generators in Querier.queryRangeRecent: error finding generators: empty ring
```

**Root Cause:** Tempo metrics generator not enabled.

**Solution:**
```bash
# Enable metrics generator in Tempo Helm values
# File: /tmp/tempo-s3-values.yaml
metricsGenerator:
  enabled: true
  replicas: 1

# Upgrade Tempo
ssh root@<CLUSTER_IP> 'helm upgrade tempo grafana/tempo-distributed \
  -n catalystlab-shared \
  -f /tmp/tempo-s3-values.yaml'

# Verify metrics generator is running
ssh root@<CLUSTER_IP> 'kubectl get pods -n catalystlab-shared -l app.kubernetes.io/component=metrics-generator'
```

### Issue: Service Graph Panels Show No Data

**Symptom:** Dashboard panels querying `traces_service_graph_*` metrics return no data.

**Causes:**
1. Tempo metrics generator not enabled
2. Prometheus not scraping Tempo metrics
3. ServiceMonitor not configured

**Solutions:**
```bash
# 1. Verify metrics generator is enabled (see above)

# 2. Check ServiceMonitor exists
ssh root@<CLUSTER_IP> 'kubectl get servicemonitor -n catalystlab-shared -l app.kubernetes.io/instance=tempo'

# 3. Verify Prometheus target
# Navigate to: http://<CLUSTER_IP>:9090/targets
# Look for: catalystlab-shared/tempo-metrics-generator

# 4. Query metrics directly from Prometheus
ssh root@<CLUSTER_IP> 'kubectl exec -n monitoring prometheus-stack-kube-prom-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=traces_service_graph_request_total" | jq .'
```

### Issue: Missing GenAI Attributes in Trace View

**Symptom:** Traces appear in Tempo but don't show `gen_ai.*` attributes (model, tokens, etc.)

**Root Cause:** LlamaStack not instrumented with OpenTelemetry wrapper.

**Solution:**
Verify llamastack deployment uses `opentelemetry-instrument` wrapper:
```bash
# Check process command
ssh root@<CLUSTER_IP> 'kubectl exec -n catalystlab-shared deploy/llamastack -c llamastack -- ps aux | grep llama'

# Expected: Command includes opentelemetry-instrument
# If not, check deployment manifest has:
command: ["opentelemetry-instrument", "llama", "stack", "run"]
args: ["/etc/llama-stack/config.yaml"]
```

## Operations

### Update Datasource Configuration

Datasources are managed by the kube-prometheus-stack Helm chart via ConfigMap.

**File:** `prometheus-stack-kube-prom-grafana-datasource` ConfigMap

```bash
# Edit datasource ConfigMap
ssh root@<CLUSTER_IP> 'kubectl edit cm prometheus-stack-kube-prom-grafana-datasource -n monitoring'

# Restart Grafana to reload config
ssh root@<CLUSTER_IP> 'kubectl rollout restart deployment prometheus-stack-grafana -n monitoring'
```

### Add New Dashboard

```bash
# Method 1: Import via UI
# Navigate to: Dashboards → Import → Upload JSON file

# Method 2: ConfigMap
ssh root@<CLUSTER_IP> 'kubectl create configmap my-dashboard \
  -n monitoring \
  --from-file=my-dashboard.json \
  --dry-run=client -o yaml | kubectl apply -f -'

# Label for auto-discovery
ssh root@<CLUSTER_IP> 'kubectl label cm my-dashboard -n monitoring \
  grafana_dashboard=1'
```

### Monitor Grafana Performance

```bash
# Check Grafana pod resources
ssh root@<CLUSTER_IP> 'kubectl top pod -n monitoring -l app.kubernetes.io/name=grafana'

# View Grafana logs
ssh root@<CLUSTER_IP> 'kubectl logs -n monitoring deploy/prometheus-stack-grafana -f'

# Check datasource health
# Navigate to: Configuration → Data Sources → Test
```

## Integration with MLflow

While Grafana uses Tempo for trace visualization, MLflow continues to receive the same trace data for experiment tracking:

**Trace Flow:**
```
llamastack → OTel Collector ─┬→ MLflow (experiment #1)
                              └→ Tempo → Grafana
```

**Use Cases:**
- **MLflow UI:** Experiment tracking, trace search by session/user, request/response previews
- **Grafana/Tempo:** TraceQL queries, service graphs, latency analysis, real-time monitoring

Both systems receive enriched traces with:
- GenAI semantic conventions (model, tokens, operation)
- MLflow-specific attributes (spanType, session, user)
- Service dependency tags (peer.service)

## References

- **Grafana Tempo Datasource:** https://grafana.com/docs/grafana/latest/datasources/tempo/
- **TraceQL Documentation:** https://grafana.com/docs/tempo/latest/traceql/
- **kube-prometheus-stack:** https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack
- **Tempo Metrics Generator:** https://grafana.com/docs/tempo/latest/metrics-generator/

## Deployment Status

**Grafana Version:** Managed by kube-prometheus-stack
**Namespace:** `monitoring`
**Datasources:** Prometheus (default), Tempo, Alertmanager
**Tempo Integration:** March 17, 2026
**Metrics Generator:** Enabled March 17, 2026

**Access:**
- **Grafana UI:** `http://<CLUSTER_IP>:3000`
- **Prometheus:** `http://<CLUSTER_IP>:9090`
- **Tempo (via Grafana):** Explore → Tempo datasource
