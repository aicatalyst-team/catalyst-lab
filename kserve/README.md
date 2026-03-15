# KServe Installation (LLM Inference Service)

Installation guide for KServe with the **v0.16.0-master** builds from the aicatalyst repository. This stack provides LLM inference (e.g. vLLM) via Kubernetes InferenceServices and depends on Gateway API, Cert-Manager, Envoy Gateway, Envoy AI Gateway, and LWS.

**Lab context:** KServe / vLLM in this repo is deployed in `kserve-lab`. This README documents how to install the stack from scratch -- coordinate with the team before modifying the live deployment.

## Version Matrix

| Component | Version | Source |
|-----------|---------|--------|
| Gateway API CRDs | v1.4.0 | kubernetes-sigs/gateway-api |
| Cert-Manager | v1.17.2 | cert-manager |
| Gateway API Inference Extension (GIE) | v1.2.1 | kubernetes-sigs/gateway-api-inference-extension |
| Envoy Gateway | v1.5.7 | envoyproxy/gateway-helm |
| Envoy AI Gateway | v0.0.0-latest | envoyproxy/ai-gateway-helm |
| LeaderWorkerSet (LWS) | v0.7.0 | registry.k8s.io/lws/charts/lws |
| KServe LLMISvc CRD | v0.16.0-master | quay.io/aicatalyst/kserve-llmisvc |
| KServe LLMISvc Controller | v0.16.0-master | quay.io/aicatalyst/kserve-llmisvc-controller |

## Architecture Overview

| Component | Namespace | Purpose |
|-----------|-----------|---------|
| Gateway API CRDs | (cluster-wide) | Standard APIs for HTTP/gRPC routing |
| Cert-Manager | `cert-manager` | TLS certificates for gateways |
| Gateway API Inference Extension (GIE) | (cluster-wide) | Inference-specific Gateway API extensions |
| Envoy Gateway | `envoy-gateway-system` | Data-plane for Gateway API |
| Envoy AI Gateway | `envoy-ai-gateway-system` | AI/LLM routing and protocol handling |
| LWS | `lws-system` | Workload scaling (e.g. for inference pods) |
| KServe CRDs + Controller | `kserve` | InferenceService CRD and controller |

Inference workloads (e.g. vLLM) are typically deployed in a separate namespace such as `kserve-lab` as `InferenceService` resources.

The KServe LLMISvc controller creates the following resources for each `LLMInferenceService` CR:

- **vLLM Deployment** -- model serving pods
- **llm-d Inference Scheduler (EPP)** -- intelligent request routing (`ghcr.io/llm-d/llm-d-inference-scheduler`)
- **InferencePool** -- Gateway API Inference Extension resource
- **Service + HTTPRoute** -- networking

## Prerequisites

- `kubectl` configured for the target cluster
- `helm` 3.x
- Cluster with sufficient resources for Envoy, LWS, and KServe controller

---

## 1. Environment Preparation

Apply in order. Allow each step to complete before proceeding (especially CRD installs and Helm `--wait`).

### 1.1 Gateway API CRDs

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml
```

### 1.2 Cert-Manager

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.17.2/cert-manager.yaml
```

### 1.3 Gateway API Inference Extension (GIE)

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.2.1/manifests.yaml
```

### 1.4 Envoy Gateway

```bash
helm install eg oci://docker.io/envoyproxy/gateway-helm --version v1.5.7 -n envoy-gateway-system --create-namespace
```

### 1.5 Envoy AI Gateway

CRDs first, then the gateway:

```bash
helm upgrade -i aieg-crd oci://docker.io/envoyproxy/ai-gateway-crds-helm \
  --version v0.0.0-latest \
  --namespace envoy-ai-gateway-system \
  --create-namespace

helm upgrade -i aieg oci://docker.io/envoyproxy/ai-gateway-helm \
  --version v0.0.0-latest \
  --namespace envoy-ai-gateway-system \
  --create-namespace
```

### 1.6 LWS (Workload Scaling)

```bash
helm install lws oci://registry.k8s.io/lws/charts/lws \
  --version 0.7.0 \
  --namespace lws-system \
  --create-namespace \
  --wait --timeout 300s
```

---

## 2. Install KServe

Uses the aicatalyst OCI charts and controller image.

### 2.1 KServe LLM Inference Service CRDs

```bash
helm install kserve-llmisvc-crd oci://quay.io/aicatalyst/kserve-llmisvc/kserve-llmisvc-crd \
  --version v0.16.0-master \
  --namespace kserve \
  --create-namespace \
  --wait
```

### 2.2 KServe LLM Inference Service (controller and resources)

```bash
helm install kserve-llmisvc oci://quay.io/aicatalyst/kserve-llmisvc/kserve-llmisvc-resources \
  --version v0.16.0-master \
  --namespace kserve \
  --set kserve.llmisvc.controller.image=quay.io/aicatalyst/kserve-llmisvc-controller \
  --set kserve.llmisvc.controller.tag=v0.16.0-master-latest
```

---

## Verification

After installation, confirm core components are running:

```bash
# Gateway API CRDs
kubectl get crd gateways.gateway.networking.k8s.io

# Cert-Manager
kubectl get pods -n cert-manager

# Envoy Gateway
kubectl get pods -n envoy-gateway-system

# Envoy AI Gateway
kubectl get pods -n envoy-ai-gateway-system

# LWS
kubectl get pods -n lws-system

# KServe controller and CRDs
kubectl get pods -n kserve
kubectl get crd | grep kserve
```

Example check for a healthy KServe controller:

```bash
kubectl get pods -n kserve -l app.kubernetes.io/instance=kserve-llmisvc
```

---

## References

- [Gateway API](https://gateway-api.sigs.k8s.io/)
- [Gateway API Inference Extension (GIE)](https://github.com/kubernetes-sigs/gateway-api-inference-extension)
- [Envoy Gateway](https://gateway.envoyproxy.io/)
- [Cert-Manager](https://cert-manager.io/)
- [KServe](https://kserve.github.io/website/)
- Team images: `quay.io/aicatalyst` (KServe controller, etc.)

## llm-d EPP (Endpoint Picker) Configuration

The EPP routes inference requests to optimal vLLM pods using a plugin-based scoring pipeline. The KServe LLMISvc controller deploys an EPP scheduler (`ghcr.io/llm-d/llm-d-inference-scheduler`) alongside each model.

### Available EPP Plugins

| Plugin | Type | Description |
|--------|------|-------------|
| `precise-prefix-cache-scorer` | Scorer | KV-events-based prefix cache scoring. Subscribes to vLLM ZMQ KV events to track allocated cache blocks. Requires tokenizer sidecar + HF_TOKEN. |
| `prefix-cache-scorer` | Scorer | Simpler hash-based prefix cache scoring. No external dependencies. |
| `kv-cache-utilization-scorer` | Scorer | Load-aware routing by KV cache memory pressure (`vllm:kv_cache_usage_perc` from Prometheus). |
| `queue-scorer` | Scorer | Load-aware routing by request queue depth (`vllm:num_requests_waiting` from Prometheus). |
| `pd-profile-handler` | Handler | Prefill/Decode disaggregation. Routes to prefill or decode workers by prompt length threshold. |
| `prefill-filter` / `decode-filter` | Filter | Pod label filtering for P/D disaggregation (`llm-d.ai/workload-type`). |
| `random-picker` | Picker | Random endpoint selection. |
| `max-score-picker` | Picker | Selects endpoint with highest weighted score. |
| `single-profile-handler` | Handler | Activates a single named scheduling profile for all requests. |

Plugins score endpoints 0.0-1.0, multiplied by configurable weights, aggregated by the picker. Configuration is via `EndpointPickerConfig` passed as `--config-text` on the EPP deployment args or via a ConfigMap.

### Current EPP Configuration (as of March 2026)

| Feature | gpt-oss-20b | qwen3-next-80b | qwen3-embedding-8b |
|---------|:-----------:|:---------------:|:-------------------:|
| EPP image | v0.5.0 | v0.5.0 | custom dev |
| `queue-scorer` (w=2) | Yes | Yes | Yes |
| `kv-cache-utilization-scorer` (w=2) | Yes | No | No |
| `precise-prefix-cache-scorer` (w=3) | Yes | No | No |
| `prefix-cache-scorer` (w=3) | No | Yes | Yes |
| KV events (ZMQ) | Yes | No | No |
| NixlConnector KV transfer | Yes | No | No |
| vLLM `--prefix-caching-hash-algo` | sha256_cbor | No | No |
| vLLM `--block-size` | 64 | Default | Default |

**gpt-oss-20b** has the full advanced EPP stack: precise prefix cache scoring with real-time KV event tracking from vLLM, plus load-aware routing via both KV cache utilization and queue depth metrics. This is the reference configuration for production-grade EPP.

**qwen3-next-80b** and **qwen3-embedding-8b** use simpler configs with hash-based prefix caching and queue scoring. To upgrade qwen3-next-80b to the full stack, it would need:
1. vLLM args: `--prefix-caching-hash-algo sha256_cbor --block-size 64 --kv-events-config ...`
2. EPP config: Replace `prefix-cache-scorer` with `precise-prefix-cache-scorer` + add `kv-cache-utilization-scorer`
3. HF_TOKEN secret for tokenizer downloads

### Unused ConfigMaps

Two EPP ConfigMaps exist in `kserve-lab` but are not referenced by any EPP deployment:

- `llmiscv-inf-scheduler-epp-default-config` -- Default config with `random-picker` + `queue-scorer`. Superseded by inline `--config-text` on each EPP deployment.
- `custom-epp-config-pd-disaggregated` -- P/D disaggregation config with `prefill-pods`/`decode-pods` label filtering and `prefix-cache-scorer`. Prepared for future use when separate prefill/decode worker pools are deployed.

### EPP References

- [llm-d/llm-d](https://github.com/llm-d/llm-d) -- EPP source and plugin documentation
- [Gateway API Inference Extension](https://github.com/kubernetes-sigs/gateway-api-inference-extension) -- InferencePool/InferenceModel CRDs

## Caveats

- Uses aicatalyst custom builds (`v0.16.0-master`), not upstream KServe releases
- Envoy AI Gateway uses `v0.0.0-latest` -- not a stable release tag
- Prerequisites must be installed in order -- Gateway API CRDs before Envoy Gateway, etc.
- The llm-d EPP scheduler is deployed automatically by the controller -- no separate llm-d install needed
- `kserve-lab` is a shared deployment -- coordinate with the team before modifying EPP configs or vLLM args
