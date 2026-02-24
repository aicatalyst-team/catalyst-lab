# Catalyst Lab

AI Catalyst infrastructure and tooling for LLM deployment, benchmarking, and observability based on Open source projects.

## Overview

Catalyst Lab provides Kubernetes configurations and documentation for deploying a complete LLM inference stack with supporting infrastructure:

# The below isn't the final list.
- **LLM Benchmarking** - GuideLLM configurations for performance testing LLM inference endpoints
- **Vector Database** - PostgreSQL with pgvector extension for embedding storage and similarity search
- **Model Serving** - KServe integration for scalable model deployment
- **Observability** - MLflow integration for LLM monitoring and prompt management

## Components

### GuideLLM Benchmarking

Kubernetes Job configurations for running [GuideLLM](https://github.com/vllm-project/guidellm) benchmarks against vLLM and KServe inference endpoints.

**Features:**
- OpenAI-compatible API benchmarking
- Multiple load profiles (sweep, constant, poisson, concurrent, throughput)
- Metrics: TTFT, ITL, end-to-end latency, throughput
- Over-saturation detection
- Results output in JSON, CSV, and HTML formats

**Location:** [`guidellm/`](./guidellm)

[View Documentation →](./guidellm/README.md)

### PostgreSQL + pgvector

Production-ready PostgreSQL 17 deployment with pgvector extension using the CloudNativePG operator.

**Features:**
- Vector similarity search with HNSW indexing
- CloudNativePG operator for automated management
- Configurable resource allocation
- Persistent storage with local-path provisioner
- Auto-generated credentials

**Location:** [`pgvector/`](./pgvector)

[View Documentation →](./pgvector/README.md)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Kubernetes Cluster                       │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐         ┌─────────────┐                   │
│  │   GuideLLM   │────────▶│   KServe    │                   │
│  │  Benchmark   │         │ Inference   │                   │
│  │     Job      │         │  Service    │                   │
│  └──────────────┘         └─────────────┘                   │
│         │                        │                           │
│         │                        ▼                           │
│         │                  ┌──────────┐                      │
│         │                  │   vLLM   │                      │
│         │                  │  Engine  │                      │
│         │                  └──────────┘                      │
│         │                                                     │
│         ▼                                                     │
│  ┌──────────────┐         ┌─────────────┐                   │
│  │  Benchmark   │         │ PostgreSQL  │                   │
│  │   Results    │         │  pgvector   │                   │
│  │     PVC      │         │   Cluster   │                   │
│  └──────────────┘         └─────────────┘                   │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

- Kubernetes cluster (1.24+)
- kubectl configured with cluster access
- Helm 3.x
- Sufficient cluster resources:
  - CPU: 4+ cores available
  - Memory: 8+ GB available
  - Storage: 30+ GB available

## Quick Start

### 1. Deploy PostgreSQL with pgvector

```bash
# Install CloudNativePG operator
helm repo add cnpg https://cloudnative-pg.github.io/charts
helm repo update
helm install cnpg cnpg/cloudnative-pg \
  --namespace cnpg-system \
  --create-namespace

# Deploy the database cluster
kubectl create namespace catalystlab-shared
kubectl apply -f pgvector/cluster.yaml
```

Verify deployment:

```bash
kubectl get cluster -n catalystlab-shared
```

### 2. Run LLM Benchmarks

```bash
# Create benchmark namespace
kubectl create namespace guide-llm

# Create PVC for results (create the YAML first)
kubectl apply -f guidellm/pvc.yaml

# Update benchmark-job.yaml with your endpoint details, then:
kubectl apply -f guidellm/benchmark-job.yaml

# Monitor progress
kubectl logs -f job/guidellm-benchmark -n guide-llm
```

## Configuration

### GuideLLM

Before running benchmarks, update `guidellm/benchmark-job.yaml`:

- **Line 18:** Replace `<inference-endpoint>:<port>` with your vLLM/KServe endpoint
- **Line 20:** Replace `<model-name>` with your model identifier
- **Line 33:** Replace `<hf-model-id>` with the HuggingFace tokenizer model ID

Example values:
```yaml
- "--target"
- "http://vllm-inference.model-serving.svc.cluster.local:8000"
- "--model"
- "meta-llama/Llama-3.1-8B-Instruct"
- "--processor"
- "meta-llama/Llama-3.1-8B-Instruct"
```

### pgvector

The PostgreSQL cluster is configured in `pgvector/cluster.yaml`:

- **Node selector:** Targets `worker-gpu2` - modify for your cluster
- **Storage:** 20Gi with `local-path` storage class
- **Resources:** 1-4 CPU cores, 2-4Gi memory
- **Instances:** Single instance (no HA)

To deploy on different nodes, update the `nodeSelector` field.

## Repository Structure

```
catalyst-lab/
├── guidellm/               # LLM benchmarking configurations
│   ├── README.md          # GuideLLM documentation
│   ├── benchmark-job.yaml # Kubernetes Job for benchmarks
│   ├── namespace.yaml     # Namespace definition
│   └── pvc.yaml           # PersistentVolumeClaim for results
├── pgvector/              # PostgreSQL + pgvector deployment
│   ├── README.md          # pgvector documentation
│   └── cluster.yaml       # CloudNativePG cluster definition
├── LICENSE                # Repository license
└── README.md              # This file
```

## Integration with Other Projects

### MLflow (Observability)

[MLflow](https://mlflow.org/docs/latest/ml/mlflow-3/) provides LLM observability, prompt management, and evaluation metrics. Deploy it to monitor your inference endpoints and track model performance.

### KServe (Model Serving)

[KServe](https://github.com/aicatalyst-team/kserve) enables standardized, scalable model serving on Kubernetes. Use it to deploy vLLM-backed inference services that GuideLLM can benchmark.

## Usage Examples

### Running a Quick Benchmark

```bash
# One-off benchmark pod (no PVC needed)
kubectl run guidellm-bench --rm -it \
  --image=ghcr.io/vllm-project/guidellm:latest \
  --restart=Never \
  -n guide-llm \
  --env="GUIDELLM__TARGET=http://your-endpoint:8000" \
  --env="GUIDELLM__MODEL=your-model-name" \
  --env="GUIDELLM__DATA=prompt_tokens=256,output_tokens=128" \
  --env="GUIDELLM__MAX_SECONDS=60"
```

### Connecting to pgvector

```bash
# Get database credentials
kubectl get secret pgvector-cluster-app -n catalystlab-shared \
  -o jsonpath='{.data.password}' | base64 -d && echo

# Port-forward for local access
kubectl port-forward -n catalystlab-shared svc/pgvector-cluster-rw 5432:5432

# Connect with psql
psql -h localhost -U vectordb -d vectordb
```

## Troubleshooting

### GuideLLM Connection Issues

If benchmarks fail to connect:

```bash
# Test endpoint from within the cluster
kubectl run curl-test --rm -it --image=curlimages/curl --restart=Never -n guide-llm -- \
  curl -s http://your-endpoint:8000/v1/models
```

### pgvector Cluster Not Ready

Check cluster status and events:

```bash
kubectl describe cluster pgvector-cluster -n catalystlab-shared
kubectl get pods -n catalystlab-shared
kubectl logs -n catalystlab-shared pgvector-cluster-1
```

### Insufficient Resources

Check resource availability:

```bash
kubectl describe nodes
kubectl top nodes
```

## Roadmap

- [ ] Add NetworkPolicy configurations for security isolation
- [ ] Helm charts for easier deployment and customization
- [ ] Kustomize overlays for dev/staging/prod environments
- [ ] Automated backup configurations for pgvector
- [ ] ServiceMonitor for Prometheus integration
- [ ] Example CI/CD pipelines
- [ ] Multi-tenant deployment examples

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/improvement`)
3. Test your changes in a Kubernetes cluster
4. Commit your changes (`git commit -am 'Add new feature'`)
5. Push to the branch (`git push origin feature/improvement`)
6. Create a Pull Request

## License

See [LICENSE](./LICENSE) for details.

## Resources

- [GuideLLM Documentation](https://github.com/vllm-project/guidellm)
- [CloudNativePG Operator](https://cloudnative-pg.io/)
- [pgvector Extension](https://github.com/pgvector/pgvector)
- [KServe Documentation](https://kserve.github.io/website/)
- [vLLM Documentation](https://docs.vllm.ai/)

## Support

For issues and questions:
- Open an issue in this repository
- Check component-specific READMEs for detailed documentation
- Review upstream project documentation for component-specific issues
