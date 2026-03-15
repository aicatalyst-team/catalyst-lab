# Scripts

Operational scripts for the AI Catalyst Lab.

## Demo & Visualization

### `demo-scenario.sh`

Generates traffic through the full AI stack and prints URLs for all observability views.

```bash
# Full demo (requires cluster access)
./scripts/demo-scenario.sh

# Print commands without executing
./scripts/demo-scenario.sh --dry-run

# Just show observability URLs
./scripts/demo-scenario.sh --urls-only

# Skip GuideLLM benchmark burst
./scripts/demo-scenario.sh --skip-benchmark
```

Steps:
1. Sends 3 A2A queries to labdemo-agent (health check, architecture, logs)
2. Sends a direct chat completion to LLaMA Stack
3. Runs a quick GuideLLM burst (10 requests at 2 req/s)
4. Prints URLs for Grafana, Jaeger, Kiali, MLflow, Kagent UI

### `export-grafana-dashboard.sh`

Exports the "AI Catalyst Lab Overview" Grafana dashboard to `grafana/catalyst-lab-overview.json`.

```bash
kubectl port-forward -n monitoring svc/grafana 3000:3000 &
./scripts/export-grafana-dashboard.sh
```

## Benchmarking

### `run-benchmark-sweep.sh`

Runs GuideLLM benchmarks at multiple concurrency levels (1, 2, 4, 8) for paper evaluation data.

```bash
# Run benchmarks at concurrency 1, 2, 4, 8 (60s each)
./scripts/run-benchmark-sweep.sh

# Preview without executing
./scripts/run-benchmark-sweep.sh --dry-run

# Run and upload results to MLflow
./scripts/run-benchmark-sweep.sh --upload-to-mlflow
```

### `guidellm_to_mlflow.py`

Parses a GuideLLM JSON report and logs the benchmark metrics to MLflow. Designed to be run as a post-processing step after benchmark jobs.

**Prerequisites:**
```bash
uv pip install mlflow
```

**Usage:**
```bash
export MLFLOW_TRACKING_URI="http://mlflow.catalystlab-shared.svc.cluster.local:5000"

# Process a single report
uv run scripts/guidellm_to_mlflow.py path/to/report.json --experiment-name "benchmark-results"

# Process a directory of reports
uv run scripts/guidellm_to_mlflow.py path/to/reports/dir/
```

**What it logs:**
- **Parameters:** backend, target, model, concurrency level
- **Metrics:** `throughput_req_per_sec`, `throughput_tok_per_sec`, `ttft_mean_ms`, `ttft_p99_ms`, `itl_mean_ms`, `itl_p99_ms`, `e2e_latency_mean_ms`
- **Artifacts:** The raw JSON report file for deep dives

## Pre-commit

### `check-sensitive-data.py`

Scans files for IP addresses, email addresses, and hardcoded credentials. Runs automatically as a pre-commit hook.
