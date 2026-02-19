# Benchmarking LLM Inference with GuideLLM

## Overview

[GuideLLM](https://github.com/vllm-project/guidellm) (v0.5.3) is a benchmarking tool by the vLLM project for evaluating LLM inference performance under realistic workload conditions. It measures latency distributions, throughput characteristics, and token-level statistics across various load patterns.

### Why GuideLLM for Our Stack

GuideLLM communicates with any **OpenAI-compatible HTTP API** via its `OpenAIHTTPBackend`. Since vLLM exposes `/v1/chat/completions` (and `/v1/completions`) natively, GuideLLM works directly against it regardless of how vLLM is deployed — standalone, behind KServe, or behind Llama Stack.

**Our inference path:**

```
GuideLLM  -->  KServe InferenceService (OpenAI route)  -->  vLLM (serving engine)
```

KServe with vLLM backend exposes OpenAI-compatible endpoints by default. GuideLLM simply needs the correct URL to that endpoint.

### Compatibility Summary

| Component    | Compatible | Notes |
|-------------|-----------|-------|
| vLLM         | Yes (recommended) | Primary backend GuideLLM is built for |
| KServe       | Yes | Any OpenAI-compatible endpoint works; point `--target` at the KServe route |
| Llama Stack  | Yes | When using vLLM as the inference provider, the OpenAI-compatible API is available |

## Prerequisites

- Python 3.10 - 3.13
- Linux or macOS (Windows via WSL)
- Minimum 2GB RAM on the benchmarking client
- Network access to the inference endpoint
- A running vLLM inference service (standalone or via KServe)

## Installation

### Option 1: pip (recommended)

```bash
# Basic
pip install guidellm

# Recommended (includes performance and tokenizer extras)
pip install guidellm[recommended]

# Full (all optional features including multimodal)
pip install guidellm[all]
```

### Option 2: From source

```bash
pip install git+https://github.com/vllm-project/guidellm.git
```

### Option 3: Container

```bash
podman run \
  --rm -it \
  -v "./results:/results:rw" \
  -e GUIDELLM_TARGET=http://<endpoint>:8000 \
  -e GUIDELLM_PROFILE=sweep \
  -e GUIDELLM_MAX_SECONDS=30 \
  -e GUIDELLM_DATA="prompt_tokens=256,output_tokens=128" \
  ghcr.io/vllm-project/guidellm:latest
```

## Determining Your Target URL

The `--target` URL depends on how your inference is deployed.

### Standalone vLLM

```bash
--target "http://<vllm-host>:8000"
```

### KServe InferenceService

KServe exposes an OpenAI-compatible route. The URL pattern is typically:

```bash
# Internal cluster access
--target "http://<isvc-name>.<namespace>.svc.cluster.local"

# External access via Istio ingress (or OpenShift Route)
--target "https://<isvc-name>-<namespace>.<domain>"
```

To find the URL:

```bash
# Get the InferenceService URL
kubectl get inferenceservice <name> -n <namespace> -o jsonpath='{.status.url}'

# Or via oc on OpenShift
oc get inferenceservice <name> -n <namespace> -o jsonpath='{.status.url}'
```

If your KServe endpoint requires authentication, pass the token via `--backend-kwargs`:

```bash
--backend-kwargs '{"api_key": "<your-token>"}'
```

### Llama Stack with vLLM

Llama Stack with vLLM as the inference provider exposes an OpenAI-compatible `/v1/chat/completions` endpoint directly. Point GuideLLM's `--target` at the Llama Stack service URL — no separate vLLM endpoint is needed.

```bash
--target "http://llamastack.<namespace>.svc.cluster.local:8321"
```

## Running Benchmarks

### Quick Start — Synthetic Data

Run a sweep benchmark with synthetic data (no dataset required):

```bash
guidellm benchmark \
  --target "http://<endpoint>:8000" \
  --model "<model-name>" \
  --data "prompt_tokens=256,output_tokens=128" \
  --max-seconds 120
```

### Sweep Profile (Default)

The sweep profile automatically discovers optimal performance points:

1. Runs a **synchronous** baseline (one request at a time)
2. Runs a **throughput** baseline (maximum parallel requests)
3. Interpolates rates between the two baselines
4. Runs benchmarks at each interpolated rate

```bash
guidellm benchmark \
  --target "http://<endpoint>:8000" \
  --model "<model-name>" \
  --data "prompt_tokens=512,output_tokens=256" \
  --profile sweep \
  --rate 10 \
  --max-seconds 60 \
  --output-dir ./results \
  --outputs json,csv,html
```

The `--rate` option in sweep mode controls the number of interpolated benchmarks (default: 10).

### Constant Rate

Send requests at a fixed rate (e.g., 5 requests/second):

```bash
guidellm benchmark \
  --target "http://<endpoint>:8000" \
  --model "<model-name>" \
  --data "prompt_tokens=256,output_tokens=128" \
  --profile constant \
  --rate 5 \
  --max-seconds 120
```

### Poisson Distribution

Simulate realistic traffic with Poisson-distributed arrivals:

```bash
guidellm benchmark \
  --target "http://<endpoint>:8000" \
  --model "<model-name>" \
  --data "prompt_tokens=256,output_tokens=128" \
  --profile poisson \
  --rate 10 \
  --max-seconds 120
```

### Concurrent Requests

Run a fixed number of parallel request streams:

```bash
guidellm benchmark \
  --target "http://<endpoint>:8000" \
  --model "<model-name>" \
  --data "prompt_tokens=256,output_tokens=128" \
  --profile concurrent \
  --rate 8 \
  --max-seconds 120
```

### Throughput Test

Find the maximum throughput the endpoint can sustain:

```bash
guidellm benchmark \
  --target "http://<endpoint>:8000" \
  --model "<model-name>" \
  --data "prompt_tokens=256,output_tokens=128" \
  --profile throughput \
  --max-seconds 120
```

## Data Sources

### Synthetic Data

Configure synthetic prompts with statistical distributions:

```bash
# Simple
--data "prompt_tokens=256,output_tokens=128"

# With distribution control
--data '{"prompt_tokens": 512, "prompt_tokens_stdev": 50, "output_tokens": 256, "output_tokens_stdev": 30, "samples": 2000}'
```

### HuggingFace Datasets

```bash
--data "openai/gsm8k" --data-args '{"split": "test"}'
```

### Local Files

Supports JSON, CSV, JSONL, and TXT:

```bash
--data "/path/to/prompts.jsonl"
```

Use `--data-column-mapper` to map dataset columns:

```bash
--data-column-mapper '{"text_column": "prompt", "output_tokens_count_column": "expected_tokens"}'
```

## Over-Saturation Detection

Automatically stops benchmarks when the model is overloaded. Monitors concurrent request growth and TTFT degradation:

```bash
guidellm benchmark \
  --target "http://<endpoint>:8000" \
  --model "<model-name>" \
  --data "prompt_tokens=256,output_tokens=128" \
  --profile sweep \
  --detect-saturation \
  --max-seconds 120
```

Advanced configuration:

```bash
--over-saturation '{"min_seconds": 30, "confidence": 0.95}'
```

## Metrics Collected

GuideLLM reports statistical distributions (mean, median, p95, p99, min, max) for:

| Metric | Description |
|--------|-------------|
| **TTFT** | Time to First Token — latency until the first token is generated |
| **ITL** | Inter-Token Latency — time between consecutive tokens |
| **E2E Latency** | End-to-end request latency |
| **Throughput** | Requests/second and tokens/second |
| **Concurrency** | Number of simultaneous in-flight requests |

## Output Formats

Specify with `--outputs` and `--output-dir`:

```bash
--output-dir ./results --outputs json,csv,html
```

| Format | File | Description |
|--------|------|-------------|
| **Console** | (stdout) | Live progress and summary tables |
| **JSON** | `benchmarks.json` | Full benchmark data — configuration, metadata, per-run stats |
| **CSV** | `benchmarks.csv` | Tabular view with throughput, latency percentiles, token counts |
| **HTML** | `benchmarks.html` | Interactive charts — latency distributions, throughput curves |

## Running from a Kubernetes Pod

Running GuideLLM inside the cluster is the recommended approach when benchmarking KServe endpoints — it eliminates ingress overhead and gives you true service-to-service latency numbers.

### Kubernetes Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: guidellm-benchmark
  namespace: <benchmark-namespace>
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: guidellm
          image: ghcr.io/vllm-project/guidellm:latest
          env:
            - name: GUIDELLM__TARGET
              value: "http://<isvc-name>.<model-namespace>.svc.cluster.local"
            - name: GUIDELLM__MODEL
              value: "<model-name>"
            - name: GUIDELLM__DATA
              value: "prompt_tokens=512,output_tokens=256"
            - name: GUIDELLM__PROFILE
              value: "sweep"
            - name: GUIDELLM__MAX_SECONDS
              value: "180"
            - name: GUIDELLM__OUTPUTS
              value: "json,csv"
          volumeMounts:
            - name: results
              mountPath: /results
          resources:
            requests:
              cpu: "2"
              memory: 2Gi
            limits:
              cpu: "4"
              memory: 4Gi
      volumes:
        - name: results
          persistentVolumeClaim:
            claimName: benchmark-results-pvc
```

Apply it:

```bash
kubectl apply -f guidellm-job.yaml
kubectl logs -f job/guidellm-benchmark -n <benchmark-namespace>
```

### Using a PVC for Results

Create a PVC to persist benchmark outputs:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: benchmark-results-pvc
  namespace: <benchmark-namespace>
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
```

Results are written to `/results` inside the container. After the job completes, retrieve them:

```bash
# Option 1: Copy from a helper pod that mounts the same PVC
kubectl cp <pod-name>:/results ./local-results -n <benchmark-namespace>

# Option 2: Use a one-off pod to access the PVC
kubectl run results-reader --rm -it --image=busybox \
  --overrides='{"spec":{"containers":[{"name":"reader","image":"busybox","command":["sh"],"volumeMounts":[{"name":"results","mountPath":"/results"}]}],"volumes":[{"name":"results","persistentVolumeClaim":{"claimName":"benchmark-results-pvc"}}]}}' \
  -n <benchmark-namespace>
```

### Quick One-Off Pod (No PVC)

For a quick test where you only need console output:

```bash
kubectl run guidellm-bench --rm -it \
  --image=ghcr.io/vllm-project/guidellm:latest \
  --restart=Never \
  -n <benchmark-namespace> \
  --env="GUIDELLM__TARGET=http://<isvc-name>.<model-namespace>.svc.cluster.local" \
  --env="GUIDELLM__MODEL=<model-name>" \
  --env="GUIDELLM__DATA=prompt_tokens=256,output_tokens=128" \
  --env="GUIDELLM__MAX_SECONDS=60"
```

### Targeting KServe Internal URLs

When running inside the cluster, use the internal service DNS name instead of the external route:

```bash
# Internal (preferred from a pod — no ingress/TLS overhead)
http://<isvc-name>.<namespace>.svc.cluster.local

# Find it:
kubectl get inferenceservice <name> -n <namespace> \
  -o jsonpath='{.status.address.url}'
```

This gives you raw service-to-service performance without ingress controller or TLS termination latency.

### Network Policies

If your cluster uses NetworkPolicies, ensure the benchmark pod namespace can reach the model-serving namespace on the vLLM port (typically 8080 or 8000).

## Deploying the Benchmark on Kubernetes

This section walks through running GuideLLM as a Kubernetes Job against a Llama Stack inference endpoint in the `labdemo` namespace.

**Target endpoint:** `http://<inference-endpoint>:<port>`
**Model:** `<model-name>`

### Step 1: Create namespace and PVC

```bash
kubectl apply -f guidellm/namespace.yaml
kubectl apply -f guidellm/pvc.yaml
```

### Step 2: Verify the endpoint is reachable

Run a quick curl pod inside the cluster to confirm the model is served:

```bash
kubectl run curl-test --rm -it --image=curlimages/curl --restart=Never -n guide-llm -- \
  curl -s http://<inference-endpoint>:<port>/v1/models
```

You should see a JSON response listing `<model-name>`.

### Step 3: Run the benchmark Job

```bash
kubectl apply -f guidellm/benchmark-job.yaml
```

### Step 4: Monitor progress

```bash
kubectl logs -f job/guidellm-benchmark -n guide-llm
```

### Step 5: Retrieve results from the PVC

After the job completes, use a helper pod to copy results locally:

```bash
# Launch a helper pod that mounts the PVC
kubectl run results-reader --rm -it \
  --image=busybox \
  --restart=Never \
  -n guide-llm \
  --overrides='{
    "spec": {
      "containers": [{
        "name": "reader",
        "image": "busybox",
        "command": ["sh"],
        "stdin": true,
        "tty": true,
        "volumeMounts": [{
          "name": "results",
          "mountPath": "/results"
        }]
      }],
      "volumes": [{
        "name": "results",
        "persistentVolumeClaim": {
          "claimName": "benchmark-results-pvc"
        }
      }]
    }
  }'

# Inside the pod, list the results:
ls /results/

# Or copy results out (from a separate terminal):
kubectl cp guidellm/results-reader:/results ./local-results
```

The PVC will contain `benchmarks.json`, `benchmarks.csv`, and `benchmarks.html`.

### Cleanup

```bash
kubectl delete job guidellm-benchmark -n guide-llm
# Optionally delete the PVC and namespace:
kubectl delete pvc benchmark-results-pvc -n guide-llm
kubectl delete namespace guidellm
```

## Environment Variables

All CLI arguments can be set as environment variables with the `GUIDELLM__` prefix:

| Variable | Description |
|----------|-------------|
| `GUIDELLM__TARGET` | Target backend URL |
| `GUIDELLM__PROFILE` | Benchmark profile (`sweep`, `constant`, `poisson`, etc.) |
| `GUIDELLM__MAX_SECONDS` | Max duration per benchmark |
| `GUIDELLM__DATA` | Data source configuration |
| `GUIDELLM__OUTPUTS` | Output formats (`json,csv,html`) |
| `GUIDELLM__REQUEST_TIMEOUT` | HTTP request timeout |
| `GUIDELLM__DEFAULT_SWEEP_NUMBER` | Number of benchmarks in sweep mode |

## CLI Reference

```bash
# Run a benchmark
guidellm benchmark run [OPTIONS]

# Preprocess a dataset
guidellm preprocess dataset DATA OUTPUT_PATH [OPTIONS]

# Start a mock server for testing
guidellm mock-server

# Show configuration / environment variables
guidellm config
```

## Troubleshooting

### Connection refused

Verify the endpoint is reachable from the benchmarking client:

```bash
curl -s <target-url>/v1/models | jq .
```

### Model not found

List available models on the endpoint:

```bash
curl -s <target-url>/v1/models | jq '.data[].id'
```

Use the exact model ID returned in your `--model` argument.

### KServe returns 403/401

Pass authentication via backend kwargs:

```bash
--backend-kwargs '{"api_key": "your-token"}'
```

Or set the bearer token for KServe routes configured with authentication.

### Custom API paths

If your KServe or proxy uses non-standard paths, you can customize the API routes in GuideLLM's backend configuration.

## References

- [GuideLLM GitHub](https://github.com/vllm-project/guidellm)
- [vLLM Documentation](https://docs.vllm.ai/)
- [KServe Documentation](https://kserve.github.io/website/)
