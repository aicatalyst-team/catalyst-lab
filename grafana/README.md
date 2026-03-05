# Grafana Dashboards

## AI Catalyst Lab Overview

**UID:** `catalyst-lab-overview`

10-panel dashboard providing a unified view of the AI stack:

| # | Panel | Type | Data Source |
|---|-------|------|-------------|
| 1 | Service Graph | Node Graph | Tempo (service graph metrics) |
| 2 | Agent Request Rate | Time Series | Prometheus (`traces_spanmetrics_calls_total`) |
| 3 | LLM Inference Latency | Histogram | Prometheus (`traces_spanmetrics_latency_bucket`) |
| 4 | Service Graph Request Rates | Bar Gauge | Prometheus (`traces_service_graph_request_total`) |
| 5 | Active Agent Services | Stat | Prometheus |
| 6 | Total LLM Calls | Stat | Prometheus |
| 7 | Error Rate | Stat | Prometheus |
| 8 | Service-to-Service Latency P50 | Table | Prometheus (`traces_service_graph_request_*`) |
| 9 | Agent Span Counts by Operation | Stacked Bars | Prometheus |
| 10 | Recent Traces | Table | Tempo |

### Planned Additions (Observability Cost Panels)

Two panels to visualize the observability noise story for the paper/demo:

**Panel 11: OTel Spans Before/After Filtering**

Shows the rate of probe spans that the OTel collector drops vs. total span throughput. Visualizes the "108 spans/min to 0" claim.

```promql
# Total span rate (all spans reaching the collector)
sum(rate(otelcol_receiver_accepted_spans[5m]))

# Approximate probe span rate (before filtering)
# Based on: 9 agents x 4 polls/min x 3 spans/poll = 108 spans/min
# Plus LLaMA Stack probe traffic (~30 spans/min)
# These are dropped by filter/drop-probes and don't appear in exporter metrics
sum(rate(otelcol_processor_dropped_spans{processor="filter/drop-probes"}[5m]))
```

**Panel 12: Signal-to-Noise Ratio**

Percentage of exported spans that are real user/agent requests vs. total received.

```promql
# Signal ratio = exported / received
sum(rate(otelcol_exporter_sent_spans[5m]))
/
sum(rate(otelcol_receiver_accepted_spans[5m]))
* 100
```

## Export / Import

### Export from live Grafana

```bash
# Port-forward to Grafana
kubectl port-forward -n monitoring svc/grafana 3000:3000 &

# Run export script
./scripts/export-grafana-dashboard.sh
```

### Import to Grafana

```bash
GRAFANA_URL="http://grafana.<INGRESS_IP>.nip.io"

curl -X POST "${GRAFANA_URL}/api/dashboards/db" \
  -H "Content-Type: application/json" \
  -d @grafana/catalyst-lab-overview.json
```

### Prerequisites

The dashboard requires these Grafana data sources to be configured:
- **Prometheus** -- for `traces_spanmetrics_*` and `traces_service_graph_*` metrics (pushed by Tempo's metrics generator via remote write)
- **Tempo** -- for trace queries and the node graph panel
