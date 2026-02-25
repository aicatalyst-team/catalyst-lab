# Istio Service Mesh Deployment on Kubernetes

> 📝 **CONFIGURATION NOTE**: This README uses placeholders for environment-specific values. Before deployment, update configurations with your cluster's external IP. Replace `<CLUSTER_IP>` in examples with your nginx ingress external IP.

> 🔒 **SECURITY WARNING**: This deployment is configured for lab/development use only. It uses anonymous authentication and lacks TLS/HTTPS encryption. **Do NOT use in production without implementing security enhancements.** See [Security Considerations](#security-considerations) section.

Deploy Istio service mesh to enable advanced traffic management, observability, and security features for services in the `catalystlab-shared` namespace. This deployment integrates with existing Prometheus for metrics collection and Jaeger for distributed tracing.

**Target cluster:** `<CLUSTER_IP>`
**Primary namespace:** `istio-system` (control plane)
**Application namespace:** `catalystlab-shared` (sidecar injection enabled)

## Why Istio?

Istio provides service mesh capabilities that complement the existing observability stack:

| Feature | Without Istio | With Istio |
|---------|---------------|------------|
| Service-to-service encryption | ❌ Plaintext | ✅ mTLS available |
| Traffic metrics | ❌ Limited | ✅ Rich metrics (latency, throughput, errors) |
| Service topology visualization | ❌ Static | ✅ Real-time (via Kiali) |
| Circuit breaking | ❌ Application-level only | ✅ Mesh-level policies |
| Request routing | ❌ Basic K8s services | ✅ Advanced routing (canary, A/B) |
| Distributed tracing | ✅ Manual instrumentation | ✅ Automatic trace propagation |

**Use Istio for**: Real-time traffic monitoring, service mesh observability, advanced routing, security policies

## Prerequisites

Before deploying Istio, verify that the following components are available on your Kubernetes cluster.

### Verification Commands

Run these commands against your cluster to verify prerequisites:

```bash
# Check Helm is installed
helm version

# Check namespace exists
kubectl get namespace catalystlab-shared

# Check existing deployments
kubectl get deployments -n catalystlab-shared

# Check Prometheus for metrics collection
kubectl get pods -n monitoring | grep prometheus

# Check available resources
kubectl describe nodes | grep -A 5 "Allocated resources"
```

### Expected Results

#### 1. Helm

**Version:** 3.x or later
```
version.BuildInfo{Version:"v3.x.x", ...}
```

Helm is required for installing Istio charts.

#### 2. Namespace

**Namespace:** `catalystlab-shared`
```
NAME                 STATUS   AGE
catalystlab-shared   Active   ...
```

#### 3. Existing Services

**Deployments:**
```
NAME             READY   UP-TO-DATE   AVAILABLE   AGE
llamastack       1/1     1            1           ...
jaeger           1/1     1            1           ...
mlflow           1/1     1            1           ...
otel-collector   1/1     1            1           ...
```

Services that will receive Istio sidecars (llamastack) and services to exclude from injection (jaeger, mlflow, otel-collector).

#### 4. Prometheus

**Pod in monitoring namespace:**
```
NAME                                                     READY   STATUS
prometheus-prometheus-stack-kube-prom-prometheus-0       2/2     Running
```

Prometheus is required for Istio metrics collection. The ServiceMonitor will configure Prometheus to scrape Istio metrics.

#### 5. Node Resources

Ensure sufficient resources for Istio control plane and sidecars:

| Component | CPU Request | Memory Request | CPU Limit | Memory Limit |
|-----------|-------------|----------------|-----------|--------------|
| istiod (per replica) | 500m | 1Gi | 1000m | 2Gi |
| istio-proxy (per pod) | 100m | 128Mi | 500m | 256Mi |

**Minimum cluster capacity:**
- CPU: 2+ cores available
- Memory: 4Gi+ available

## Prerequisites Summary

| Component | Status | Details |
|-----------|--------|---------|
| Helm 3.x | ✅ Required | For installing Istio charts |
| Namespace | ✅ Required | `catalystlab-shared` must exist |
| Prometheus | ✅ Required | For metrics collection |
| Node Resources | ✅ Required | Sufficient CPU/memory for control plane + sidecars |
| Existing Services | ✅ Required | llamastack, jaeger, mlflow, otel-collector running |

## Deployment

### Step 1: Add Istio Helm Repository

```bash
helm repo add istio https://istio-release.storage.googleapis.com/charts
helm repo update
```

Verify repository added:

```bash
helm search repo istio
```

Expected output should show `istio/base`, `istio/istiod`, etc.

### Step 2: Create istio-system Namespace

```bash
kubectl create namespace istio-system
```

This namespace will host the Istio control plane components.

### Step 3: Install Istio Base Components

```bash
helm install istio-base istio/base -n istio-system --set defaultRevision=default
```

Verify installation:

```bash
helm list -n istio-system
kubectl get crds | grep istio
```

Expected: Istio CRDs created (VirtualService, DestinationRule, Gateway, etc.)

### Step 4: Install Istiod (Control Plane)

```bash
helm install istiod istio/istiod -n istio-system -f istio-values.yaml
```

Monitor the deployment:

```bash
kubectl get pods -n istio-system -w
```

Wait for istiod pod to reach `Running` status (typically 1-2 minutes).

Check logs for any errors:

```bash
kubectl logs -n istio-system -l app=istiod --tail=50
```

### Step 5: Enable Sidecar Injection for catalystlab-shared

```bash
kubectl label namespace catalystlab-shared istio-injection=enabled --overwrite
```

Verify the label:

```bash
kubectl get namespace catalystlab-shared --show-labels
```

Expected output should include `istio-injection=enabled`.

### Step 6: Exclude Observability Pods from Injection

Observability components should NOT have sidecars to avoid circular dependencies:

```bash
# Exclude Jaeger
kubectl patch deployment jaeger -n catalystlab-shared -p '{"spec":{"template":{"metadata":{"annotations":{"sidecar.istio.io/inject":"false"}}}}}'

# Exclude OTel Collector
kubectl patch deployment otel-collector -n catalystlab-shared -p '{"spec":{"template":{"metadata":{"annotations":{"sidecar.istio.io/inject":"false"}}}}}'

# Exclude MLflow
kubectl patch deployment mlflow -n catalystlab-shared -p '{"spec":{"template":{"metadata":{"annotations":{"sidecar.istio.io/inject":"false"}}}}}'

# Exclude Tempo (if deployed)
kubectl patch deployment tempo -n catalystlab-shared -p '{"spec":{"template":{"metadata":{"annotations":{"sidecar.istio.io/inject":"false"}}}}}'
```

### Step 7: Restart llamastack to Inject Sidecar

```bash
kubectl rollout restart deployment llamastack -n catalystlab-shared
kubectl rollout status deployment llamastack -n catalystlab-shared
```

Wait for rollout to complete. The llamastack pod should now have 2/2 containers (app + istio-proxy).

Verify sidecar injection:

```bash
kubectl get pods -n catalystlab-shared -l app=llamastack
```

Expected output:
```
NAME                          READY   STATUS    RESTARTS   AGE
llamastack-xxxxx-xxxxx        2/2     Running   0          1m
```

### Step 8: Configure Prometheus for Istio Metrics

Apply the ServiceMonitor and PodMonitor to enable Prometheus scraping:

```bash
kubectl apply -f servicemonitor.yaml
```

Verify resources created:

```bash
kubectl get servicemonitor -n istio-system istio-component-monitor
kubectl get podmonitor -n istio-system envoy-stats-monitor
```

## Verification

### 1. Verify Istio Control Plane

Check istiod health:

```bash
kubectl get pods -n istio-system
```

Expected: All pods in `Running` status.

Check istiod logs for errors:

```bash
kubectl logs -n istio-system -l app=istiod --tail=20 | grep -i error
```

Expected: No critical errors.

### 2. Verify Sidecar Injection

Check llamastack pod:

```bash
kubectl get pod -n catalystlab-shared -l app=llamastack -o jsonpath='{.items[0].spec.containers[*].name}'
```

Expected output: `llamastack istio-proxy` (or similar - 2 containers)

Check sidecar logs:

```bash
POD=$(kubectl get pod -n catalystlab-shared -l app=llamastack -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n catalystlab-shared $POD -c istio-proxy --tail=20
```

Expected: Envoy proxy initialization logs, no errors.

### 3. Verify Prometheus Metrics

Wait 30-60 seconds for first scrape, then check metrics:

```bash
kubectl exec -n monitoring prometheus-prometheus-stack-kube-prom-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=istio_requests_total" | \
  jq '.data.result | length'
```

Expected: Number > 0 (after traffic flows through llamastack)

### 4. Test Traffic Flow

Generate test traffic to populate metrics:

```bash
POD=$(kubectl get pod -n catalystlab-shared -l app=llamastack -o jsonpath='{.items[0].metadata.name}')

# Send test request through llamastack
kubectl exec -n catalystlab-shared $POD -c llamastack -- \
  curl -s http://localhost:8321/v1/models
```

Wait 10-20 seconds, then check Envoy metrics:

```bash
kubectl exec -n catalystlab-shared $POD -c istio-proxy -- \
  pilot-agent request GET stats/prometheus | grep istio_requests_total | head -5
```

Expected: Metrics showing request counts.

## Deployment Status

Use these commands to verify your deployment:

```bash
# Check control plane
kubectl get pods,svc -n istio-system

# Check sidecar injection
kubectl get pods -n catalystlab-shared

# Check namespace labels
kubectl get namespace catalystlab-shared --show-labels

# Check Prometheus integration
kubectl get servicemonitor,podmonitor -n istio-system
```

### Access Information

- **Istio Control Plane:** `istiod.istio-system.svc.cluster.local:15012`
- **Prometheus Metrics:** Scraped automatically via ServiceMonitor/PodMonitor
- **Sidecar Metrics:** Available on each injected pod at `:15020/stats/prometheus`

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Istio Control Plane (istio-system namespace)               │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ istiod                                               │  │
│  │ - Service discovery                                  │  │
│  │ - Configuration distribution                         │  │
│  │ - Certificate authority (mTLS)                       │  │
│  │ - Sidecar injection webhook                          │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ Config push (xDS protocol)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Application Namespace (catalystlab-shared)                  │
│                                                             │
│  ┌────────────────────────────────────────┐                │
│  │ llamastack Pod                         │                │
│  │  ┌──────────────┐  ┌────────────────┐ │                │
│  │  │ llamastack   │  │ istio-proxy    │ │                │
│  │  │ container    │◄─┤ (Envoy sidecar)│ │                │
│  │  │              │  │                │ │                │
│  │  │  :8321       │  │  :15001 (out)  │─┼──► vLLM       │
│  │  │              │  │  :15006 (in)   │ │                │
│  │  │              │  │  :15020 (stats)│─┼──► Prometheus  │
│  │  └──────────────┘  └────────────────┘ │                │
│  └────────────────────────────────────────┘                │
│                                                             │
│  ┌────────────────────────────────────────┐                │
│  │ Observability Pods (NO sidecars)       │                │
│  │  - jaeger                              │                │
│  │  - mlflow                              │                │
│  │  - otel-collector                      │                │
│  │  - tempo                               │                │
│  └────────────────────────────────────────┘                │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ Metrics scraping
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Monitoring Namespace                                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Prometheus                                           │  │
│  │ - Scrapes istiod metrics (ServiceMonitor)           │  │
│  │ - Scrapes Envoy sidecar metrics (PodMonitor)        │  │
│  │ - Stores: istio_requests_total, latency, etc.       │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Data flow:**
1. istiod watches Kubernetes API for services, pods, configurations
2. istiod pushes configuration to all Envoy sidecars via xDS protocol
3. Traffic to/from llamastack flows through istio-proxy sidecar
4. Envoy sidecar collects metrics (requests, latency, errors)
5. Prometheus scrapes Envoy metrics from `:15020/stats/prometheus`
6. Metrics available for Kiali visualization and alerting

## Integration with Existing Components

### Jaeger (Distributed Tracing)

Istio is configured to send traces to Jaeger:

**Configuration in istio-values.yaml:**
```yaml
meshConfig:
  defaultConfig:
    tracing:
      zipkin:
        address: "jaeger-collector.catalystlab-shared.svc.cluster.local:9411"
```

**Trace flow:**
1. llamastack makes request with trace context
2. Envoy sidecar propagates trace headers (B3, traceparent)
3. Traces sent to Jaeger Collector (Zipkin format on port 9411)
4. View traces in Jaeger UI showing service mesh layer

### Prometheus (Metrics)

ServiceMonitor and PodMonitor configure Prometheus to scrape Istio metrics:

**Metrics collected:**
- `istio_requests_total` - Total requests by service
- `istio_request_duration_milliseconds` - Request latency distribution
- `istio_tcp_connections_opened_total` - TCP connection metrics
- Many more...

**Query examples:**
```promql
# Request rate to vLLM
rate(istio_requests_total{destination_service_name="qwen3-next-80b-kserve-workload-svc"}[5m])

# 95th percentile latency
histogram_quantile(0.95, rate(istio_request_duration_milliseconds_bucket[5m]))
```

### OTel Collector

OTel Collector continues to receive application-level traces from llamastack. These are independent of Istio's service mesh traces:

- **Application traces**: Detailed spans from llamastack code (LLM calls, prompts, responses)
- **Mesh traces**: Network-level spans from Envoy (HTTP requests, latencies)

Both appear in Jaeger and can be correlated via trace IDs.

## Troubleshooting

### Istiod Pod Not Starting

Check pod events:

```bash
kubectl describe pod -n istio-system -l app=istiod
```

Common issues:
- Insufficient resources (increase node capacity)
- Image pull errors (check network/registry access)
- CRDs not installed (reinstall istio-base)

### Sidecar Not Injected

Check namespace label:

```bash
kubectl get namespace catalystlab-shared --show-labels
```

Expected: `istio-injection=enabled`

Check webhook:

```bash
kubectl get mutatingwebhookconfigurations | grep istio
```

Expected: `istio-sidecar-injector` present

Force re-injection:

```bash
kubectl rollout restart deployment llamastack -n catalystlab-shared
```

### Application Fails After Sidecar Injection

Check sidecar logs:

```bash
POD=$(kubectl get pod -n catalystlab-shared -l app=llamastack -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n catalystlab-shared $POD -c istio-proxy --tail=50
```

Common issues:
- Port conflicts (Istio reserves ports 15000-15099)
- mTLS issues (use `PERMISSIVE` mode for mixed environments)
- Health probe failures (configure probes correctly)

**Disable mTLS if needed:**

```bash
kubectl apply -f - <<EOF
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: catalystlab-shared
spec:
  mtls:
    mode: PERMISSIVE
EOF
```

### No Metrics in Prometheus

Check ServiceMonitor/PodMonitor labels:

```bash
kubectl get servicemonitor -n istio-system istio-component-monitor -o yaml | grep -A 5 labels
```

Expected: `release: prometheus-stack` (matches Prometheus label selector)

Check Prometheus targets:

```bash
# Port-forward Prometheus UI
kubectl port-forward -n monitoring prometheus-prometheus-stack-kube-prom-prometheus-0 9090:9090

# Open http://localhost:9090/targets
# Look for istio-component-monitor and envoy-stats-monitor
```

If targets missing, verify:
- ServiceMonitor/PodMonitor created in correct namespace
- Label selectors match
- Prometheus ServiceMonitor selector includes istio-system namespace

### High Memory Usage

Envoy sidecars can consume memory based on traffic volume.

Check current usage:

```bash
kubectl top pods -n catalystlab-shared --containers | grep istio-proxy
```

Adjust resource limits if needed by editing deployment or using pod annotations:

```yaml
metadata:
  annotations:
    sidecar.istio.io/proxyCPU: "200m"
    sidecar.istio.io/proxyMemory: "256Mi"
    sidecar.istio.io/proxyCPULimit: "500m"
    sidecar.istio.io/proxyMemoryLimit: "512Mi"
```

## Security Considerations

> ⚠️ **CRITICAL**: This deployment has security limitations. Read carefully before deploying.

### Current Security Posture

**✅ Security Features Enabled:**
- Service-to-service communication monitored
- Traffic metrics and observability

**❌ Security Features NOT Enabled:**
- **mTLS**: Not enforced (mode: PERMISSIVE or disabled)
  - **Risk**: Unencrypted service-to-service communication
- **Authorization Policies**: Not configured
  - **Risk**: No access control between services
- **Network Policies**: Not implemented
  - **Risk**: Pods can communicate freely

### Acceptable Use

**This deployment is acceptable for:**
- Lab/development environments
- Internal testing
- Learning Istio features
- Proof-of-concept

**This deployment is NOT acceptable for:**
- Production environments with sensitive data
- Multi-tenant environments
- Compliance-regulated workloads
- Internet-facing services

### Security Enhancement Roadmap

**Minimum (Development):**
1. Enable mTLS in PERMISSIVE mode
2. Implement basic authorization policies
3. Add network policies

**Recommended (Staging):**
1. Enable mTLS in STRICT mode
2. Implement RBAC with service accounts
3. Enable request authentication (JWT)
4. Configure egress controls

**Required (Production):**
1. Enforce mTLS STRICT mode
2. Fine-grained authorization policies per service
3. Request authentication with external identity provider
4. Network policies with default-deny
5. Audit logging enabled
6. Regular security scanning
7. Certificate rotation policies

### Quick Security Improvements

**Enable mTLS (5 minutes):**

```bash
kubectl apply -f - <<EOF
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: catalystlab-shared
spec:
  mtls:
    mode: STRICT
EOF
```

**Add Authorization Policy (10 minutes):**

```bash
# Example: Only allow llamastack to call vLLM
kubectl apply -f - <<EOF
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: vllm-access
  namespace: kserve-lab
spec:
  action: ALLOW
  rules:
  - from:
    - source:
        principals: ["cluster.local/ns/catalystlab-shared/sa/llamastack"]
EOF
```

## Uninstalling Istio

### Step 1: Remove Sidecar Injection

```bash
# Remove namespace label
kubectl label namespace catalystlab-shared istio-injection-

# Restart pods to remove sidecars
kubectl rollout restart deployment llamastack -n catalystlab-shared
```

Verify sidecars removed:

```bash
kubectl get pods -n catalystlab-shared -l app=llamastack
```

Expected: `1/1` containers (sidecar removed)

### Step 2: Delete Prometheus Integration

```bash
kubectl delete servicemonitor istio-component-monitor -n istio-system
kubectl delete podmonitor envoy-stats-monitor -n istio-system
```

### Step 3: Uninstall Istio Components

```bash
helm uninstall istiod -n istio-system
helm uninstall istio-base -n istio-system
```

### Step 4: Delete Namespace

```bash
kubectl delete namespace istio-system
```

**Note**: This removes all Istio CRDs, configurations, and resources.

### Verify Cleanup

```bash
kubectl get all -n istio-system
kubectl get crds | grep istio
kubectl get namespace catalystlab-shared --show-labels
```

All Istio resources should be removed. Existing services (llamastack, jaeger, mlflow) continue to function normally.

## References

- [Istio Documentation](https://istio.io/latest/docs/)
- [Istio Helm Installation](https://istio.io/latest/docs/setup/install/helm/)
- [Istio Observability](https://istio.io/latest/docs/tasks/observability/)
- [Istio Security](https://istio.io/latest/docs/concepts/security/)
- [Envoy Proxy](https://www.envoyproxy.io/docs/envoy/latest/)
