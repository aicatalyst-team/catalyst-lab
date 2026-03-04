# AI Catalyst Lab -- Architecture Diagram

> **Legend:** Curly braces `{...}` indicate gaps between current and target state.
> Nodes without curly braces are fully live. Dashed lines = not yet connected/deployed.

---

## Mermaid Diagram

```mermaid
graph TB
    %% ============================================================
    %% CLIENTS / USERS
    %% ============================================================
    subgraph Clients ["Clients"]
        WEBUI["`**Open WebUI**
*ns: open-webui*`"]
        GUIDELLM["`**GuideLLM**
Completed benchmarks for Qwen3-Next-80B
*ns: guide-llm*`"]
        CURL["`**curl / SDK clients**`"]
        KAGENT_UI["`**Kagent UI**
http://kagent.<INGRESS_IP>.nip.io
*ns: kagent*`"]
    end

    %% ============================================================
    %% AGENT LAYER
    %% ============================================================
    subgraph AgentLayer ["Agent Layer -- ns: kagent"]
        KAGENT_CTRL["`**Kagent Controller**
CRD controller + A2A server
*image: cr.kagent.dev/kagent-dev/kagent/app:0.7.18*`"]

        KAGENT_AGENTS["`**10 Built-in Agents**
k8s, istio, helm, promql, kgateway,
argo-rollouts, observability, 3x cilium
All Ready, OTel auto-injected`"]

        KAGENT_TOOLS["`**kagent-tools**
MCP tool server (kubectl, helm)
Scoped RBAC: read-only cluster-wide,
write in catalystlab-shared`"]
    end

    %% ============================================================
    %% INFERENCE GATEWAY LAYER
    %% ============================================================
    subgraph InferenceGW ["Inference Gateway Layer"]
        LLAMASTACK["`**LLaMA Stack**
image: quay.io/aicatalyst/llamastack-starter:0.5.1-patched
Istio sidecar injected (mTLS)
tool calling: verified
Agents API: hotfixed (baked in image)
RAG: embedding provider + pgvector connected
*ns: catalystlab-shared, :8321*`"]
    end

    %% ============================================================
    %% MODEL SERVING LAYER
    %% ============================================================
    subgraph ModelServing ["Model Serving Layer -- ns: kserve-lab"]
        KSERVE_CTRL["`**KServe + LLMISvc Controller**
LLMInferenceService CRD
*ns: kserve*`"]

        LLMD_EPP["`**llm-d Inference Scheduler (EPP)**
v0.4.0 / v0.5.0
*image: ghcr.io/llm-d/llm-d-inference-scheduler*
{Gap: P/D disaggregation, KV offload,
wide EP, variant autoscaling
not configured}`"]

        VLLM_QWEN["`**vLLM: Qwen3-Next-80B**
RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8
1 replica, TP=2, tool calling enabled
workload-svc :8000`"]

        VLLM_EMBED["`**vLLM: Qwen3-Embedding-8B**
Embedding model (3rd on MTEB)
1 replica, workload-svc :8000`"]
    end

    %% ============================================================
    %% OBSERVABILITY LAYER
    %% ============================================================
    subgraph Observability ["Observability Layer"]
        OTEL["`**OTel Collector**
image: collector-contrib:latest
Owned by infra team
filter/drop-probes + transform + batch
Fan-out: MLflow + Jaeger + Tempo
*ns: catalystlab-shared, :4317/:4318*`"]

        MLFLOW["`**MLflow**
Trace ingestion, PVC artifact store
span type: FIXED via OTTL
{Gap: request/response preview EMPTY
-- blocked on upstream openai-v2
SPAN_AND_EVENT mode}
*ns: catalystlab-shared, :5000*`"]

        JAEGER["`**Jaeger**
Traces + dependency graph (12 services)
{Gap: Content inspection not working
-- needs LoggerProvider + logs pipeline}
*ns: catalystlab-shared*`"]

        TEMPO["`**Tempo**
Grafana-native tracing backend
Service graphs via metrics generator
Grafana datasource configured
*ns: catalystlab-shared, :3200*`"]

        KIALI["`**Kiali**
Istio service mesh topology
http://kiali.<INGRESS_IP>.nip.io
*ns: kiali*`"]

        GRAFANA["`**Grafana**
Prometheus + Tempo datasources
*ns: monitoring*`"]

        PROMETHEUS["`**Prometheus**
kube-prometheus-stack
*ns: monitoring*`"]
    end

    %% ============================================================
    %% DATA LAYER
    %% ============================================================
    subgraph DataLayer ["Data Layer -- ns: catalystlab-shared"]
        PG["`**PostgreSQL (CNPG)**
pgvector-cluster, 1 replica`"]

        PG_VECTORDB["`**DB: vectordb**
pgvector for LLaMA Stack vector_io`"]
        PG_LLAMASTACK["`**DB: llamastack**
LLaMA Stack KV + SQL store`"]
        PG_MLFLOW["`**DB: mlflow**
MLflow metadata`"]

        PG --> PG_VECTORDB
        PG --> PG_LLAMASTACK
        PG --> PG_MLFLOW
    end

    %% ============================================================
    %% INFRASTRUCTURE (abbreviated)
    %% ============================================================
    subgraph Infra ["Infrastructure"]
        ENVOY["`**Envoy AI Gateway**`"]
        INGRESS["`**Ingress NGINX**`"]
        CNPG_OP["`**CNPG Operator**`"]
        KSERVE_OP["`**KServe Operator**`"]
        ISTIO["`**Istio Ambient + Sidecar**`"]
    end

    %% ============================================================
    %% EDGES -- INFERENCE FLOW
    %% ============================================================
    WEBUI -->|"HTTP :8321"| LLAMASTACK
    GUIDELLM -->|"HTTP :8321"| LLAMASTACK
    CURL -->|"HTTP :8321"| LLAMASTACK
    KAGENT_UI -->|"A2A JSON-RPC"| KAGENT_AGENTS

    KAGENT_AGENTS -->|"HTTP :8321
via LLaMA Stack OpenAI API"| LLAMASTACK

    LLAMASTACK -->|"OpenAI-compat API
HTTP -> workload-svc:8000"| LLMD_EPP

    LLMD_EPP -->|"EPP ext-proc via Envoy"| VLLM_QWEN

    LLAMASTACK -.->|"{Pending: configure
embedding provider}"| VLLM_EMBED

    KSERVE_CTRL -->|"Deploys vLLM + EPP"| LLMD_EPP
    KSERVE_CTRL -->|"Manages"| VLLM_QWEN
    KSERVE_CTRL -->|"Manages"| VLLM_EMBED

    %% ============================================================
    %% EDGES -- OBSERVABILITY FLOW
    %% ============================================================
    LLAMASTACK -->|"OTLP gRPC :4317"| OTEL

    KAGENT_AGENTS -->|"OTLP gRPC :4317
auto-injected by controller"| OTEL

    OTEL -->|"OTLP/HTTP :5000"| MLFLOW

    OTEL -->|"OTLP/gRPC :4317"| JAEGER

    OTEL -->|"OTLP/gRPC :4317"| TEMPO

    TEMPO -->|"remote_write
service graphs"| PROMETHEUS

    PROMETHEUS -->|"Datasource"| GRAFANA
    TEMPO -->|"Datasource"| GRAFANA
    ISTIO -->|"Mesh topology"| KIALI

    %% ============================================================
    %% EDGES -- DATA FLOW
    %% ============================================================
    LLAMASTACK -->|"TCP :5432
llamastack DB + vectordb"| PG
    MLFLOW -->|"TCP :5432
mlflow DB"| PG

    %% ============================================================
    %% STYLING
    %% ============================================================
    classDef live fill:#d4edda,stroke:#28a745,stroke-width:2px,color:#000
    classDef partial fill:#fff3cd,stroke:#ffc107,stroke-width:2px,color:#000

    class VLLM_QWEN,VLLM_EMBED,PG,PG_VECTORDB,PG_LLAMASTACK,PG_MLFLOW,GUIDELLM,WEBUI,CURL,GRAFANA,PROMETHEUS,ENVOY,INGRESS,CNPG_OP,KSERVE_OP,KSERVE_CTRL,KAGENT_CTRL,KAGENT_AGENTS,KAGENT_UI,TEMPO,KIALI,ISTIO live
    class LLAMASTACK,OTEL,MLFLOW,JAEGER,LLMD_EPP,KAGENT_TOOLS partial
```

---

## Node Reference Table

| Component | Namespace | Status | {Gaps} |
|-----------|-----------|--------|--------|
| **Kagent Controller** | kagent | LIVE | -- |
| **Kagent Agents (10)** | kagent | LIVE | All 10 Ready, OTel auto-injected |
| **Kagent Tools** | kagent | PARTIAL | cluster-admin RBAC needs scoping to read-only + namespace-scoped write |
| **Kagent UI** | kagent | LIVE | Ingress at `kagent.<INGRESS_IP>.nip.io` |
| **LLaMA Stack** | catalystlab-shared | PARTIAL | Tool calling verified, Agents API hotfixed, RAG registered. Pending: configure embedding provider for qwen3-embedding-8b. |
| **llm-d Inference Scheduler (EPP)** | kserve-lab | PARTIAL | EPP routing live (v0.4.0/v0.5.0). Advanced features not configured: P/D disaggregation, KV-cache offloading, wide expert parallelism, variant autoscaling. |
| **vLLM: Qwen3-Next-80B** | kserve-lab | LIVE | 1 replica, TP=2, tool calling enabled (hermes parser). CrashLoop resolved. |
| **vLLM: Qwen3-Embedding-8B** | kserve-lab | LIVE | Embedding model, 3rd on MTEB leaderboard. Deployed by Sean. |
| **OTel Collector** | catalystlab-shared | LIVE | Probe filter + OTTL transforms + batch. Fan-out to MLflow + Jaeger + Tempo. Owned by infra team. |
| **MLflow** | catalystlab-shared | PARTIAL | Span type FIXED. Request/response preview EMPTY (blocked on upstream openai-v2 `SPAN_AND_EVENT` mode). |
| **Jaeger** | catalystlab-shared | PARTIAL | Traces + dependency graph working (12 services). Content inspection not working (needs LoggerProvider + logs pipeline). |
| **Tempo** | catalystlab-shared | LIVE | Grafana-native tracing. Service graph metrics via `metrics_generator` -> Prometheus. Grafana datasource configured. Deployed by Gerald. |
| **Kiali** | kiali | LIVE | Istio service mesh topology visualization. Deployed by Gerald. |
| **Grafana** | monitoring | LIVE | Prometheus + Tempo datasources. |
| **Prometheus** | monitoring | LIVE | -- |
| **PostgreSQL (CNPG)** | catalystlab-shared | LIVE | -- |
| **GuideLLM** | guide-llm | LIVE | -- |
| **Open WebUI** | open-webui | LIVE | -- |
| **KServe + LLMISvc** | kserve | LIVE | -- |
| **Envoy AI Gateway** | envoy-ai-gateway-system | LIVE | -- |

---

## Edge Reference Table

| From | To | Protocol / Port | Status | {Gaps} |
|------|----|----------------|--------|--------|
| Open WebUI | LLaMA Stack | HTTP :8321 | LIVE | -- |
| GuideLLM | LLaMA Stack | HTTP :8321 | LIVE | -- |
| curl / SDK | LLaMA Stack | HTTP :8321 | LIVE | -- |
| Kagent UI | Kagent Agents | A2A JSON-RPC | LIVE | -- |
| Kagent Agents | LLaMA Stack | HTTP :8321 | LIVE | Via ModelConfig -> OpenAI-compatible API |
| LLaMA Stack | llm-d EPP -> vLLM Qwen3 | HTTP :8000 | LIVE | -- |
| LLaMA Stack | vLLM Qwen3-Embedding-8B | HTTP :8000 | PENDING | Embedding provider not yet configured in LLaMA Stack |
| llm-d EPP | vLLM Qwen3 | Envoy ext-proc | PARTIAL | Basic routing active. Advanced scheduling not configured. |
| KServe ctrl | vLLM pods + EPP | K8s API | LIVE | -- |
| LLaMA Stack | OTel Collector | OTLP gRPC :4317 | LIVE | Traces flowing. No logs pipeline. |
| Kagent Agents | OTel Collector | OTLP gRPC :4317 | LIVE | Auto-injected by controller. |
| OTel Collector | MLflow | OTLP/HTTP :5000 | LIVE | Span type FIXED via OTTL. Request/response preview EMPTY. |
| OTel Collector | Jaeger | OTLP/gRPC :4317 | LIVE | Traces + dependency graph working. Logs not flowing. |
| OTel Collector | Tempo | OTLP/gRPC :4317 | LIVE | Fan-out via collector pipeline. |
| Tempo | Prometheus | remote_write | LIVE | Service graph metrics. |
| Tempo | Grafana | Datasource | LIVE | -- |
| Prometheus | Grafana | Datasource | LIVE | -- |
| Istio | Kiali | Mesh API | LIVE | -- |
| LLaMA Stack | PostgreSQL | TCP :5432 | LIVE | -- |
| MLflow | PostgreSQL | TCP :5432 | LIVE | -- |

---

## Gap Summary

### Gaps in Deployed Components
1. **LLaMA Stack** -- Embedding provider not configured for qwen3-embedding-8b (needed for RAG)
2. **Kagent Tools RBAC** -- cluster-admin needs scoping to cluster-wide read + catalystlab-shared write
3. **llm-d EPP** -- Basic routing only; P/D disaggregation, KV offload, wide EP, variant autoscaling not configured
4. **MLflow** -- Request/response preview empty (blocked on upstream openai-v2 `SPAN_AND_EVENT` mode)
5. **Jaeger** -- Content inspection not working (needs LoggerProvider + logs pipeline)

### Pending Work
6. **Grafana dashboards** -- Custom dashboards for vLLM hardware metrics + LLaMA Stack HTTP metrics (deferred)
7. **Vending-Bench / advanced benchmarks** -- Scope and run count TBD (deferred)
8. **Jaeger vs Tempo consensus** -- Gerald proposed consolidating; team decision pending

---

## Component Responsibilities

| Component | Responsibility |
|-----------|---------------|
| **Kagent** | Agent orchestration platform -- CRD-based agent definitions, A2A protocol, OTel auto-injection, MCP tool routing. Zero custom code. |
| **LLaMA Stack** | Unified inference gateway -- OpenAI-compatible API, tool calling, agentic workflows, memory, RAG. Abstracts model serving from clients. |
| **KServe + LLMISvc** | Model serving orchestration -- manages vLLM deployments, llm-d EPP, InferencePool, networking via LLMInferenceService CRD. |
| **llm-d EPP** | Intelligent request routing -- routes to optimal vLLM pod based on KV-cache state, prefix cache hits, load. |
| **vLLM** | LLM inference engine -- loads model weights onto GPU, token generation, OpenAI-compatible API. |
| **OTel Collector** | Central telemetry router -- receives OTLP from all instrumented services, applies filtering/transforms, fan-out to MLflow + Jaeger + Tempo. |
| **MLflow** | Experiment tracking -- trace storage, span analysis, experiment comparison, model registry, artifact storage. |
| **Jaeger** | Distributed trace visualization -- full trace trees, service dependency graphs, latency analysis. Complements MLflow's experiment-level view. |
| **Tempo** | Grafana-native tracing -- integrates with Grafana dashboards, service graphs via metrics generator, node graph visualization. Complements Jaeger. |
| **Kiali** | Istio mesh topology -- animated service graph, traffic flow visualization, Istio configuration validation. |
| **Grafana** | Central dashboards -- metrics (Prometheus), traces (Tempo), cluster health, application metrics. |
| **Prometheus** | Metrics collection -- scrapes endpoints, time-series storage, PromQL, alerting. |
| **PostgreSQL (CNPG)** | Shared relational database -- LLaMA Stack state, MLflow metadata, pgvector for vector search. |
