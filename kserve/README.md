# KServe Installation (LLM Inference Service)

Installation guide for KServe with the **v0.16.0-master** builds from the aicatalyst repository. This stack provides LLM inference (e.g. vLLM) via Kubernetes InferenceServices and depends on Gateway API, Cert-Manager, Envoy Gateway, Envoy AI Gateway, and LWS.

**Lab context:** KServe / vLLM in this repo is deployed in `kserve-lab`. This README documents how to install the stack from scratch — **do not modify** the live `kserve-lab` deployment without coordination.

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
