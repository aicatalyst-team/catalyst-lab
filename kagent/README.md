# Kagent — CNCF Sandbox Agent Platform

Kubernetes-native agent management using CRDs. Agents are defined declaratively via `Agent` and `ModelConfig` custom resources. The controller deploys agent pods automatically with OTel tracing injected.

**Project:** [kagent-dev/kagent](https://github.com/kagent-dev/kagent) (CNCF Sandbox, Solo.io)

## Current Deployment

| Component | Version | Namespace | Status |
|-----------|---------|-----------|--------|
| Controller | 0.7.18 | `kagent` | Running |
| UI | 0.7.18 | `kagent` | Running (port 8080) |
| KMCP Controller | 0.7.18 | `kagent` | Running |
| Tools Server | 0.7.18 | `kagent` | Running |
| Engine Image | `cr.kagent.dev/kagent-dev/kagent/app:0.7.18` | — | Pulled by controller |

### Helm Releases

```bash
# CRDs (installed first)
helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
  --namespace kagent --create-namespace --version 0.7.18

# Main chart
helm install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --namespace kagent --version 0.7.18 -f kagent/values.yaml
```

### Post-Install Patch

The Helm chart template does not support `openAI.baseUrl` in the provider config. After install, patch the ModelConfig to point at LLaMA Stack:

```bash
kubectl -n kagent patch modelconfig default-model-config \
  --type merge --patch-file kagent/modelconfig-patch.yaml
```

### API Key Secret

LLaMA Stack accepts any non-empty API key. Create before install:

```bash
kubectl create secret generic kagent-openai -n kagent \
  --from-literal=OPENAI_API_KEY="catalyst-lab-internal"  # pragma: allowlist secret
```

## Built-in Agents

All agents run in `kagent` namespace, reference `default-model-config`, and use LLaMA Stack -> Qwen3-Next-80B (tool calling enabled via hermes parser).

| Agent | Purpose | Status |
|-------|---------|--------|
| `k8s-agent` | Kubernetes resource management (kubectl MCP tools) | Ready |
| `istio-agent` | Istio service mesh operations | Ready |
| `helm-agent` | Helm chart management | Ready |
| `promql-agent` | Prometheus query execution (PromQL) | Ready |
| `kgateway-agent` | Kubernetes Gateway API management | Ready |
| `argo-rollouts-conversion-agent` | Argo Rollouts progressive delivery | Ready |
| `cilium-debug-agent` | Cilium network debugging | Ready |
| `cilium-manager-agent` | Cilium network management | Ready |
| `cilium-policy-agent` | Cilium network policy management | Ready |
| `observability-agent` | Observability (Grafana) | Ready |

### Using the Agents

**Via UI:**
```bash
kubectl -n kagent port-forward svc/kagent-ui 8080:8080
# Open http://localhost:8080
```

**Via A2A API:**
```bash
kubectl -n kagent port-forward svc/kagent-controller 8083:8083
# API at http://localhost:8083/api
```

## Model Configuration

| Property | Value |
|----------|-------|
| ModelConfig name | `default-model-config` |
| Provider | OpenAI (compatible) |
| Model | `vllm/RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8` |
| Base URL | `http://llamastack.catalystlab-shared.svc.cluster.local:8321/v1` |
| API Key Secret | `kagent-openai` (dummy — LLaMA Stack accepts any non-empty key) |

**Inference path:** Agent pod -> LLaMA Stack (`:8321/v1`) -> vLLM workload svc (`:8000/v1`) -> GPU

## Observability

OTel tracing and logging are enabled. The controller injects these env vars into every agent pod:

| Env Var | Value |
|---------|-------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector.catalystlab-shared.svc.cluster.local:4317` |
| `OTEL_TRACING_ENABLED` | `true` |
| `OTEL_LOGGING_ENABLED` | `true` |

**Trace path:** Agent pod -> OTel Collector (`:4317`) -> MLflow (`:5000`)

## CRDs

| CRD | API Group | Purpose |
|-----|-----------|---------|
| `agents.kagent.dev` | `kagent.dev/v1alpha2` | Agent definitions |
| `modelconfigs.kagent.dev` | `kagent.dev/v1alpha2` | LLM provider configs |
| `mcpservers.kagent.dev` | `kagent.dev/v1alpha1` | Local MCP tool servers |
| `remotemcpservers.kagent.dev` | `kagent.dev/v1alpha2` | Remote MCP tool servers |
| `memories.kagent.dev` | `kagent.dev/v1alpha1` | Agent memory stores |
| `modelproviderconfigs.kagent.dev` | `kagent.dev/v1alpha2` | Provider-level configs |
| `toolservers.kagent.dev` | `kagent.dev/v1alpha1` | Tool server definitions |

**Important:** Do not install Kagenti (`kagenti.operator.dev` etc.) on the same cluster to avoid API ambiguity with the `agents` resource.

## Disabled Components

| Component | Why Disabled | How to Enable |
|-----------|-------------|---------------|
| `querydoc` | Needs OpenAI API key for embeddings | Set `tools.querydoc.enabled=true` + configure `querydoc.openai.apiKey` |

## Caveats

1. **ModelConfig baseUrl not in Helm template** — must be patched post-install. If you `helm upgrade`, the patch will be overwritten. Re-apply after every upgrade.
2. **All agents in `kagent` namespace** — built-in agents, ModelConfig, and secrets all live in `kagent`. The controller watches cluster-wide, so custom agents can be created in other namespaces.
3. **Dummy API key** — `kagent-openai` secret contains a placeholder. LLaMA Stack accepts any non-empty key. Not a security concern for internal cluster traffic.

## External Access

| Service | URL | Notes |
|---------|-----|-------|
| Kagent UI | `http://kagent.<INGRESS_IP>.nip.io` | nginx Ingress, WebSocket-enabled |
| Jaeger | `http://jaeger.<INGRESS_IP>.nip.io` | Trace visualization |
| MLflow | `http://mlflow.<INGRESS_IP>.nip.io` | LLM trace experiment |

## Security & RBAC

**Warning:** The `kagent-tools` ServiceAccount has **cluster-admin** ClusterRoleBinding. All MCP tool calls (kubectl operations) from agents route through the `kagent-tools` pod with full cluster access. This means any agent user can execute kubectl commands against any namespace.

| ServiceAccount | ClusterRole | Scope |
|----------------|-------------|-------|
| `kagent-tools` | `kagent-tools-cluster-admin-role` | `*/*` (all resources, all verbs) |
| `kagent-controller` | `kagent-getter-role` + `kagent-writer-role` | Agent CRD management |
| Per-agent SAs | None (cluster-wide) | Agent pods have no direct cluster RBAC |

**Risk:** The UI Ingress at `kagent.<INGRESS_IP>.nip.io` exposes this indirectly — anyone who can reach the UI can ask agents to delete resources, read secrets, or create privileged pods in any namespace.

**Mitigations for production:**
1. Restrict UI Ingress with IP allowlist or authentication
2. Scope `kagent-tools-cluster-admin-role` to specific namespaces via Roles instead of ClusterRole
3. Remove write tools from agents that don't need them (patch agent CRDs to use only read `toolNames`)

## Smoke Test Results (2026-02-26)

| Test | Agent | Duration | Result |
|------|-------|----------|--------|
| List namespaces | k8s-agent | 3,494ms | Passed — 41 namespaces, tool call + LLM inference |
| Count pods | k8s-agent | 3,016ms | Passed — 13 pods in kagent namespace |

**Trace pipeline verified:**
- Agent → OTel Collector (gRPC :4317) → MLflow + Jaeger (fan-out)
- Jaeger: 83 spans per agent interaction, service name = `k8s_agent`
- MLflow: traces appear in experiment `llamastack-traces` (ID=1)
- OTel collector filters: A2A health probes + LLaMA Stack readiness probes dropped

## Verification

```bash
# Check all agents
kubectl -n kagent get agents.kagent.dev

# Check ModelConfig
kubectl -n kagent get modelconfig default-model-config -o yaml

# Check pods
kubectl -n kagent get pods

# Controller logs
kubectl -n kagent logs -l app.kubernetes.io/component=controller -f

# Agent pod logs (example: k8s-agent)
kubectl -n kagent logs -l kagent=k8s-agent -f

# UI (external)
open http://kagent.<INGRESS_IP>.nip.io

# UI (port-forward)
kubectl -n kagent port-forward svc/kagent-ui 8080:8080
```
