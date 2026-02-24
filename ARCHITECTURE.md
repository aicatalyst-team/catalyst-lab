# Catalyst Lab Architecture

This document describes the architecture of the Catalyst Lab Kubernetes infrastructure for LLM deployment, benchmarking, and observability.

## System Architecture

```mermaid
graph TB
    subgraph External["External Services"]
        Jira[Jira]
        Github[Github]
        BraveSearch[Brave Search]
    end

    subgraph KubernetesLab["Kubernetes Lab"]
        User((User))
        Admin((Administrator))
        
        subgraph Frontend["Frontend"]
            WebUI[WebUI<br/>LLama-Stack<br/>client]
        end
        
        subgraph Orchestration["Orchestration & Agents"]
            Kagenti[Kagenti]
            BeeAI[BeeAI Agent<br/>Kagenti CRD<br/>A2A :9999]
        end
        
        subgraph Storage["Storage Layer"]
            PgVector[Vector Storage<br/>PgVector]
            Posgresql[Posgresql]
        end
        
        subgraph LLMInference["LLM Inference"]
            LlamaStack[LLAMA-STACK<br/>Server]
            KServe[KServe]
            LlmdScheduler[llm-d<br/>scheduler]
            LlmdVLLM[llm-d<br/>vLLM]
        end
        
        subgraph MCPServers["MCP Servers"]
            KuadrantMCP[Kuadrant<br/>mcp-gateway]
            GitHubMCP[GitHub<br/>MCP server]
            JiraMCP[Jira<br/>MCP server]
            SearchMCP[Search<br/>MCP Server]
            BenchmarkMCP[Benchmark<br/>MCP Server]
        end
        
        subgraph Observability["Observability & Monitoring"]
            MLFlow[MLFlow<br/>LLM Traces]
            VisualMLFlow[Visual For MLFlow<br/>TBD]
            GrafanaDash[Grafana<br/>Dashboard]
            OtelPrometheus[Observability<br/>OTel+Prometheus]
        end
        
        subgraph Benchmarking["Benchmarking"]
            AgenticBench[Agentic Benchmark:<br/>TravelPlanner/VendingBench]
        end
    end

    %% User interactions
    User <--> WebUI
    User --> AgenticBench
    Admin <--> GrafanaDash
    
    %% Frontend connections
    WebUI <--> LlamaStack
    
    %% Orchestration flow
    Kagenti --> BeeAI
    Kagenti --> VisualMLFlow
    BeeAI --> LlamaStack
    AgenticBench --> Kagenti
    
    %% LLM Inference flow
    LlamaStack --> PgVector
    LlamaStack --> Posgresql
    LlamaStack --> KServe
    KServe --> LlmdScheduler
    KServe --> LlmdVLLM
    LlmdScheduler --> LlmdVLLM
    
    %% MCP Gateway connections
    LlamaStack --> KuadrantMCP
    KuadrantMCP <--> GitHubMCP
    KuadrantMCP <--> JiraMCP
    KuadrantMCP <--> SearchMCP
    KuadrantMCP <--> BenchmarkMCP
    
    %% External service connections
    GitHubMCP <--> Github
    JiraMCP <--> Jira
    SearchMCP <--> BraveSearch
    
    %% Observability connections
    VisualMLFlow --> MLFlow
    MLFlow --> Posgresql
    MLFlow --> LlamaStack
    OtelPrometheus --> LlamaStack
    OtelPrometheus --> KServe
    GrafanaDash --> OtelPrometheus
    Kagenti --> MLFlow
    
    %% Styling
    classDef userStyle fill:#fff,stroke:#333,stroke-width:2px
    classDef frontendStyle fill:#fff,stroke:#333,stroke-width:1px
    classDef orchestrationStyle fill:#ffd700,stroke:#333,stroke-width:2px
    classDef inferenceStyle fill:#90EE90,stroke:#333,stroke-width:1px
    classDef storageStyle fill:#fff,stroke:#333,stroke-width:1px
    classDef mcpStyle fill:#E6E6FA,stroke:#333,stroke-width:1px
    classDef observabilityStyle fill:#FF6B6B,stroke:#333,stroke-width:2px
    classDef externalStyle fill:#fff,stroke:#333,stroke-width:1px
    classDef benchStyle fill:#fff,stroke:#333,stroke-width:1px
    
    class User,Admin userStyle
    class WebUI frontendStyle
    class Kagenti,BeeAI orchestrationStyle
    class KServe,LlmdScheduler,LlmdVLLM,LlamaStack inferenceStyle
    class PgVector,Posgresql storageStyle
    class KuadrantMCP,GitHubMCP,JiraMCP,SearchMCP,BenchmarkMCP mcpStyle
    class MLFlow,VisualMLFlow,GrafanaDash,OtelPrometheus observabilityStyle
    class Jira,Github,BraveSearch externalStyle
    class AgenticBench benchStyle
```

## Component Descriptions

### Frontend Layer

- **WebUI (Llama-Stack Client)**: User-facing interface for interacting with the LLM inference stack

### Orchestration & Agents

- **Kagenti**: Kubernetes-native agent orchestration system
- **BeeAI Agent**: AI agent implementation using Kagenti CRD, exposes Agent-to-Agent (A2A) interface on port 9999

### Storage Layer

- **PgVector**: PostgreSQL with pgvector extension for vector embeddings and similarity search
- **PostgreSQL**: Primary database for storing application data, traces, and metadata

### LLM Inference

- **LLAMA-STACK Server**: Core LLM inference orchestration server
- **KServe**: Kubernetes-native model serving platform for ML inference
- **llm-d Scheduler**: Custom scheduler for LLM workload management
- **llm-d vLLM**: vLLM engine for efficient LLM inference

### MCP Servers (Model Context Protocol)

- **Kuadrant MCP Gateway**: Central gateway for routing MCP requests
- **GitHub MCP Server**: Integration with GitHub APIs
- **Jira MCP Server**: Integration with Jira project management
- **Search MCP Server**: Web search integration (Brave Search)
- **Benchmark MCP Server**: Benchmarking service integration

### Observability & Monitoring

- **MLFlow**: LLM trace collection and experiment tracking
- **Visual For MLFlow**: Visualization layer for MLFlow data (TBD)
- **Grafana Dashboard**: Monitoring dashboards for administrators
- **OTel+Prometheus**: OpenTelemetry and Prometheus for metrics collection

### Benchmarking

- **Agentic Benchmark**: Benchmark suite including TravelPlanner and VendingBench for evaluating agentic AI systems

### External Services

- **GitHub**: Source code repository integration
- **Jira**: Project management and issue tracking
- **Brave Search**: Web search API for information retrieval

## Data Flow

### User Request Flow

1. User interacts with **WebUI**
2. WebUI sends requests to **LLAMA-STACK Server**
3. LLAMA-STACK routes inference requests to **KServe**
4. KServe uses **llm-d scheduler** to manage workload placement
5. Inference is executed by **llm-d vLLM** engine
6. Results are returned to the user via LLAMA-STACK and WebUI

### Agent Orchestration Flow

1. **Agentic Benchmark** triggers tasks via **Kagenti**
2. Kagenti orchestrates **BeeAI Agent** instances
3. BeeAI communicates with **LLAMA-STACK** for LLM capabilities
4. LLAMA-STACK accesses external services via **MCP Gateway**
5. MCP servers interact with external APIs (GitHub, Jira, Search)

### Observability Flow

1. **LLAMA-STACK** and **KServe** emit OpenTelemetry traces
2. **OTel+Prometheus** collects metrics and traces
3. **MLFlow** captures LLM-specific traces and logs
4. **Grafana Dashboard** visualizes metrics for administrators
5. **Visual For MLFlow** provides LLM trace visualization

## Deployment Considerations

### Resource Requirements

- **LLM Inference (vLLM)**: GPU-enabled nodes required
- **PostgreSQL/PgVector**: Persistent storage with high I/O performance
- **Observability Stack**: Moderate CPU/memory for metrics aggregation
- **MCP Servers**: Lightweight, can run on standard nodes

### Network Architecture

- Internal service-to-service communication within Kubernetes cluster
- External ingress for WebUI and administrative interfaces
- Secure connectivity to external APIs (GitHub, Jira, Brave Search)
- A2A communication on port 9999 for agent interactions

### Storage Strategy

- **PgVector**: Vector embeddings storage (20Gi default)
- **PostgreSQL**: Application data, traces, MLFlow experiments
- **Benchmark Results**: Persistent volume claims for GuideLLM outputs

## Security Considerations

- Network policies for service isolation
- Secret management for external API credentials
- RBAC for Kubernetes resource access
- TLS/HTTPS for external endpoints
- Authentication/authorization for MCP gateway

## Scalability

- **KServe**: Horizontal scaling for inference workloads
- **vLLM**: GPU resource pooling and efficient batching
- **PostgreSQL**: Read replicas for observability queries
- **MCP Servers**: Stateless, can scale horizontally
- **Kagenti**: Distributed agent orchestration

## Future Enhancements

- Enhanced MLFlow visualization (Visual For MLFlow)
- Additional MCP server integrations
- Advanced scheduling strategies for llm-d
- Multi-cluster federation for global deployment
- Advanced security controls (mTLS, policy enforcement)
