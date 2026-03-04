# Catalyst Lab Scripts

## Benchmark Integrations

### `guidellm_to_mlflow.py`
Parses a GuideLLM JSON report and logs the benchmark metrics to MLflow. Designed to be run as a post-processing step in the GuideLLM Kubernetes Job.

**Prerequisites:**
```bash
uv pip install mlflow
```

**Usage:**
```bash
export MLFLOW_TRACKING_URI="http://mlflow.catalystlab-shared.svc.cluster.local:5000"

# Process a single report
uv run guidellm_to_mlflow.py path/to/report.json --experiment-name "benchmark-results"

# Process a directory of reports
uv run guidellm_to_mlflow.py path/to/reports/dir/
```

**What it logs:**
- **Parameters:** backend, target, model, concurrency level
- **Metrics:** `throughput_req_per_sec`, `throughput_tok_per_sec`, `ttft_mean_ms`, `ttft_p99_ms`, `itl_mean_ms`, `itl_p99_ms`, `e2e_latency_mean_ms`
- **Artifacts:** The raw JSON report file for deep dives
