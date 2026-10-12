# Tether Operator — CRD & Controller Design

Post-KaRaMeL: operator manages a single verified C binary extracted from F*/Pulse proofs.
Target: OLM bundle → OperatorHub → `oc install tether`

## CRD: TetherGateway

```yaml
apiVersion: tether.ai/v1alpha1
kind: TetherGateway
metadata:
  name: tether
  namespace: tether-verified
spec:
  # Verification configuration
  verification:
    properties:
      content: [P1, P2, P3, P4]       # F* refinement types
      substrate: [P5, P6, P7, P8]     # Pulse separation logic
      toolUse: [P9, P10]              # Tool scope + side-effect
    surfaces: [inference, skill, tool, temporal, witness]
    memoryBound: 2200                  # Tier 1 (MEMORY.md) char limit
    poisonPatterns:
      source: default                  # default | configMapRef
    tokenContainment: true             # enforce token_subset predicate

  # Inference proxy (sits at KServe boundary)
  inferenceProxy:
    enabled: true
    upstream: gemma-4-31b-predictor.ls-evals.svc.cluster.local:8443
    tls: true
    ruleClassification: true           # Identity > Extraction > Aggregation > Derivation

  # Sandbox configuration (creates the OpenShell Sandbox CR)
  sandbox:
    enabled: true
    runtimeClassName: kata             # Layer 1: kernel isolation
    openshell:                         # Layer 2: OS constraints
      seccompProfile: RuntimeDefault
      landlockReadOnly: [/opt/fstar, /opt/tether/specs]
      cgroupMemory: 2Gi
      cgroupCPU: "2"
      cgroupPIDs: 64
      privacyRouter: local_only
    networkPolicy:
      egressPorts: [4317, 4318]        # OTel only
      denyExternal: true

  # Agent binding
  agent:
    name: hermes-agent
    image: quay.io/aicatalyst/hermes-agent:latest
    memoryProvider: tether             # injects config + sidecar
    verifyWrites: true

  # Backing services (operator reconciles these)
  postgresql:
    clusterName: tether-pg-cluster
    database: tetherdb
    # Operator watches CNPG cluster, wires secrets automatically

  mlflow:
    enabled: true
    image: ghcr.io/mlflow/mlflow:v2.19.0
    artifactRoot: /tmp/mlflow-artifacts

  # Observability
  observability:
    otelCollector:
      endpoint: otel-collector.catalystlab-shared.svc.cluster.local:4317
    serviceMesh:
      enabled: true
      peerAuthentication: PERMISSIVE   # or STRICT

status:
  phase: Running                       # Pending | Running | Degraded | Failed
  verifiedBinary:
    version: "0.3.0"
    extractedFrom: "TetherPredicates.fst@abc1234"
    z3Version: "4.13.4"
  properties:
    satisfied: [P1, P2, P3, P4, P5, P7, P9, P10]
    pending: [P6, P8]
  components:
    gateway:     { ready: true,  replicas: 1 }
    sidecar:     { ready: true,  replicas: 1 }
    proxy:       { ready: true,  replicas: 1 }
    sandbox:     { ready: true,  phase: Running }
    postgresql:  { ready: true,  phase: Running }
    mlflow:      { ready: true,  replicas: 1 }
  conditions:
    - type: GatewayReady
      status: "True"
      reason: AllSpecsVerified
      message: "24/24 F* specs verified, 0 admits"
    - type: SandboxReady
      status: "True"
      reason: ThreeLayerActive
      message: "Kata + OpenShell + Tether layers active"
    - type: ProxyReady
      status: "True"
      reason: UpstreamReachable
      message: "gemma-4-31b-predictor responding"
```

## Controller Reconciliation

```text
TetherGateway CR
       │
       ├─► Sandbox CR (agents.x-k8s.io/v1beta1)
       │     └─ podTemplate with 4 containers:
       │        hermes, tether-sidecar, tether-inference-proxy, istio-proxy
       │
       ├─► Deployment (tether-gateway)
       │     └─ verified C binary (KaRaMeL-extracted)
       │        F*/Z3 engine, gRPC :50051, HTTP :8080
       │
       ├─► Deployment (mlflow) — if spec.mlflow.enabled
       │
       ├─► Service + Route (gateway, agent, proxy, mlflow)
       │     └─ auto-adds maistra.io/expose-route label
       │     └─ auto-adds excludeInboundPorts annotation
       │
       ├─► PeerAuthentication (Istio mTLS)
       │
       ├─► ConfigMaps (tether-config, tether-hermes-plugin, tether-specs)
       │
       └─► Watches CNPG Cluster CR → wires pg secrets into sidecar/gateway
```

## Key Operator Behaviors

1. **Verified binary lifecycle**: operator watches for new KaRaMeL extraction
   artifacts in a ConfigMap or OCI image tag. On update, rolls the gateway
   deployment with the new binary. Status reflects extraction provenance
   (source commit, Z3 version).

2. **Sandbox CR ownership**: operator creates and owns the Sandbox CR.
   Changes to spec.sandbox reconcile into the Sandbox CR spec. The
   Agent Sandbox Controller (agent-sandbox-system) handles the actual
   pod scheduling — Tether operator just declares intent.

3. **Service mesh integration**: operator auto-adds the maistra.io/expose-route
   label and Istio annotation exclusions learned from deployment experience
   (excludeInboundPorts for HTTP ports, excludeOutboundPorts for PostgreSQL/MLflow).

4. **Health aggregation**: status.conditions aggregates health from all
   sub-resources. Degraded if any component unhealthy. Failed if the
   verified binary fails Z3 self-check on startup.

## Scaffolding (post-KaRaMeL)

```text
operator/
├── api/v1alpha1/
│   ├── tethergateway_types.go
│   └── zz_generated.deepcopy.go
├── controllers/
│   └── tethergateway_controller.go
├── config/
│   ├── crd/bases/tether.ai_tethergateways.yaml
│   ├── rbac/
│   ├── manager/
│   └── samples/tether_v1alpha1_tethergateway.yaml
├── bundle/                            # OLM bundle for OperatorHub
│   ├── manifests/
│   └── metadata/
├── Dockerfile
├── Makefile
└── PROJECT
```

Built with operator-sdk (Go), targeting controller-runtime v0.19+.
