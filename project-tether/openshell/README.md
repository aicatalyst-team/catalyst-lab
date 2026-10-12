# OpenShell Deployment for Tether

NVIDIA OpenShell provides application-layer sandboxing (Layer 2) in the Tether three-layer security model:

| Layer | Technology | Threat Mitigated |
|-------|------------|-----------------|
| 1. Kernel | Kata Containers (OpenShift Sandboxed Containers) | Container escapes, page cache attacks |
| 2. Application | OpenShell (Landlock, seccomp, cgroups) | Data exfiltration, unauthorized network/filesystem |
| 3. Content | Tether (F*/Z3 formal verification) | Hallucination persistence, unsound reasoning |

## Prerequisites

- OpenShift AI cluster with Agent Sandbox Controller (`agent-sandbox-system`)
- OpenShift Sandboxed Containers Operator (Kata runtime)
- `quay-pull-secret` in `tether-verified` namespace
- CNPG cluster (`tether-pg-cluster`) running
- `tether-config` and `tether-hermes-plugin` ConfigMaps applied

## Deployment

```bash
# 1. Grant SCC permissions
oc apply -f openshell/scc-binding.yaml

# 2. Deploy OpenShell gateway
helm install openshell oci://ghcr.io/nvidia/openshell/helm-chart \
  --version 0.0.92 \
  --namespace tether-verified \
  -f openshell/helm-values.yaml

# 3. Apply sandbox policy
oc apply -f config/openshell-policy.yaml -n tether-verified

# 4. Create sandbox template
oc apply -f openshell/tether-sandbox-template.yaml -n tether-verified

# 5. Launch the sandbox
oc apply -f openshell/tether-sandbox.yaml -n tether-verified
```

## Verification

```bash
# Check OpenShell gateway
oc get pods -n tether-verified -l app.kubernetes.io/name=openshell

# Check sandbox status
oc get sandbox tether-hermes -n tether-verified

# Check pod is running with Kata runtime
oc get pod -n tether-verified -l tether.ai/verified=true -o jsonpath='{.items[0].spec.runtimeClassName}'
```

## Files

| File | Purpose |
|------|---------|
| `helm-values.yaml` | Helm values for OpenShell gateway deployment |
| `scc-binding.yaml` | SCC permissions for sandbox service accounts |
| `tether-sandbox-template.yaml` | SandboxTemplate defining Hermes + Tether pod |
| `tether-sandbox.yaml` | Sandbox CR to instantiate the workload |
