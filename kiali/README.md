# Kiali Service Mesh Observability

> 📝 **CONFIGURATION NOTE**: This README uses placeholders for environment-specific values. Before deployment, update `ingress.yaml` with your cluster's external IP. Replace `<CLUSTER_IP>` in examples with your nginx ingress external IP.

> ⚠️ **REQUIRES ISTIO**: Kiali provides visualization for Istio service mesh. Deploy Istio (see `../istio/README.md`) before deploying Kiali.

> 🔒 **SECURITY WARNING**: This deployment is configured for lab/development use only. It lacks authentication, TLS/HTTPS, and RBAC. **Do NOT use in production without implementing security enhancements.** See [Security Considerations](#security-considerations) section.

Deploy Kiali as the observability console for Istio service mesh in the `istio-system` namespace. This deployment integrates with Prometheus for traffic metrics and Jaeger for distributed trace correlation, providing real-time animated service topology visualization.

**Target cluster:** `<CLUSTER_IP>`
**Namespace:** `istio-system`

## Why Kiali?

Kiali provides animated service topology visualization that complements Jaeger's static dependency graphs:

| Feature | Jaeger | Kiali |
|---------|--------|-------|
| Service Dependency Graph | ✅ Static only | ✅ Real-time animated |
| Traffic Flow Animation | ❌ Not available | ✅ Excellent |
| Live Metrics (RPS, Latency) | ❌ Not available | ✅ Excellent |
| Service Health Dashboard | ❌ Limited | ✅ Comprehensive |
| Trace Integration | ✅ Native | ✅ Via external link |
| Istio Config Validation | ❌ Not available | ✅ Excellent |
| Request Rate & Error % | ❌ Not available | ✅ Real-time |
| Service-to-Service mTLS | ❌ Not available | ✅ Visual indicators |

**Use Jaeger for**: Detailed trace analysis, waterfall views, trace search
**Use Kiali for**: Real-time service topology, traffic visualization, Istio troubleshooting, service health monitoring

## Prerequisites

Before deploying Kiali, verify that the following components are available on your Kubernetes cluster.

### Verification Commands

Run these commands against your cluster to verify prerequisites:

```bash
# Check namespace exists
kubectl get namespace istio-system

# Check Istio control plane
kubectl get deployment -n istio-system istiod
kubectl get svc -n istio-system istiod

# Check Nginx Ingress Controller
kubectl get ingressclass
kubectl get svc -n ingress-nginx

# Check Prometheus
kubectl get svc -n monitoring prometheus-stack-kube-prom-prometheus

# Check Jaeger (optional but recommended for trace correlation)
kubectl get svc -n catalystlab-shared jaeger-query

# Verify Istio sidecars are injected
kubectl get pods -n catalystlab-shared -l app=llamastack
```

### Expected Results

#### 1. Namespace

**Namespace:** `istio-system`
```
NAME           STATUS   AGE
istio-system   Active   ...
```

#### 2. Istio Control Plane

**Deployment:**
```
NAME      READY   UP-TO-DATE   AVAILABLE   AGE
istiod    1/1     1            1           ...
```

**Service:**
```
NAME     TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)                                 AGE
istiod   ClusterIP   10.x.x.x     <none>        15010/TCP,15012/TCP,443/TCP,15014/TCP   ...
```

#### 3. Nginx Ingress Controller

**IngressClass:**
```
NAME    CONTROLLER             PARAMETERS   AGE
nginx   k8s.io/ingress-nginx   <none>       ...
```

**Service with external IP:**
```
NAME                       TYPE           EXTERNAL-IP      PORT(S)
ingress-nginx-controller   LoadBalancer   <CLUSTER_IP>   80:31123/TCP,443:31755/TCP
```

**External IP:** `<CLUSTER_IP>` - Used for constructing the Kiali ingress hostname.

#### 4. Prometheus

**Service:**
```
NAME                                      TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)    AGE
prometheus-stack-kube-prom-prometheus     ClusterIP   10.x.x.x     <none>        9090/TCP   ...
```

Kiali queries Prometheus for Istio metrics (request rates, latencies, error rates).

**Verify Istio metrics in Prometheus:**
```bash
kubectl exec -n monitoring prometheus-stack-kube-prom-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=istio_requests_total" | jq ".data.result | length"
```

Should return > 0 if Istio ServiceMonitor/PodMonitor are configured (see `../istio/servicemonitor.yaml`).

#### 5. Jaeger (Optional)

**Service:**
```
NAME           TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)     AGE
jaeger-query   ClusterIP   10.x.x.x     <none>        16686/TCP   ...
```

Kiali can link to Jaeger for viewing distributed traces.

#### 6. Istio Sidecar Injection

**Example pod with sidecar:**
```
NAME                          READY   STATUS    RESTARTS   AGE
llamastack-xxx-yyy            2/2     Running   0          ...
```

**2/2 containers**: application + istio-proxy sidecar

Without sidecars, Kiali cannot visualize traffic (Istio metrics come from Envoy proxies).

## Prerequisites Summary

| Component | Status | Details |
|-----------|--------|---------|
| Namespace | ✅ Required | `istio-system` must exist |
| Istio Control Plane | ✅ Required | istiod deployment running |
| Nginx Ingress | ✅ Required | External IP: `<CLUSTER_IP>` |
| Prometheus | ✅ Required | URL: `http://prometheus-stack-kube-prom-prometheus.monitoring.svc.cluster.local:9090` |
| Istio Metrics | ✅ Required | ServiceMonitor/PodMonitor configured |
| Jaeger | ⚠️ Optional | Recommended for trace correlation |
| Sidecar Injection | ✅ Required | At least one namespace with sidecars |

## Deployment

### Installation Method

Kiali can be deployed via:
1. **Helm Chart** (recommended for new deployments)
2. **Istio integration** (bundled with Istio installation)
3. **Manual manifests** (this repository provides manifests)

This guide covers **Helm installation** as used in the current deployment.

### Step 1: Add Kiali Helm Repository

```bash
helm repo add kiali https://kiali.org/helm-charts
helm repo update
```

### Step 2: Install Kiali Server

Deploy Kiali using the provided Helm values:

```bash
# From repository root
helm install kiali-server kiali/kiali-server \
  -n istio-system \
  -f kiali/kiali-values.yaml
```

Monitor the deployment:

```bash
kubectl get pods -n istio-system -l app.kubernetes.io/name=kiali -w
```

Wait for the pod to reach `Running` status.

Check logs for any errors:

```bash
kubectl logs -n istio-system -l app.kubernetes.io/name=kiali --tail=50
```

### Step 3: Deploy Kiali Ingress

Expose Kiali UI via NGINX ingress:

```bash
kubectl apply -f kiali/ingress.yaml
```

Verify the ingress:

```bash
kubectl get ingress -n istio-system kiali
```

Expected output should show the hostname `kiali.<CLUSTER_IP>.nip.io`.

### Step 4: Verify Kiali Configuration

Check that Kiali is configured with Prometheus and Jaeger integration:

```bash
kubectl get configmap -n istio-system kiali -o yaml | grep -A 5 "prometheus:"
kubectl get configmap -n istio-system kiali -o yaml | grep -A 10 "tracing:"
```

Expected configuration (from `kiali-values.yaml`):
- **Prometheus URL**: `http://prometheus-stack-kube-prom-prometheus.monitoring.svc.cluster.local:9090`
- **Jaeger in-cluster URL**: `http://jaeger-query.catalystlab-shared.svc.cluster.local:16686`
- **Jaeger external URL**: `http://jaeger.<CLUSTER_IP>.nip.io`

## Verification

### 1. Access Kiali UI

Open in browser:

```
http://kiali.<CLUSTER_IP>.nip.io
```

You should see the Kiali dashboard with:
- **Graph** tab (service topology)
- **Applications** tab
- **Workloads** tab
- **Services** tab
- **Istio Config** tab

### 2. Health Check

```bash
curl -I http://kiali.<CLUSTER_IP>.nip.io
```

Expected: `HTTP 200 OK`

### 3. Verify Prometheus Integration

In Kiali UI:
1. Go to **Graph** tab
2. Select namespace (e.g., `catalystlab-shared`)
3. If you see "No Graph Data", check:
   - Prometheus connection (should be automatic)
   - Traffic flow (generate test traffic)
   - Sidecar injection (verify pods have 2/2 containers)

Test Prometheus connection from Kiali pod:

```bash
kubectl exec -n istio-system -l app.kubernetes.io/name=kiali -- \
  curl -I http://prometheus-stack-kube-prom-prometheus.monitoring.svc.cluster.local:9090
```

Expected: `HTTP 200 OK`

### 4. Verify Jaeger Integration

In Kiali UI:
1. Go to **Graph** tab
2. Select namespace with traffic
3. Click on an **edge** (connection between services)
4. In the side panel, click **Traces** tab
5. Click **View in Tracing**

Should open Jaeger UI in a new tab showing traces for that service pair.

### 5. Test Animated Service Topology

Generate continuous traffic:

```bash
# Generate traffic to llamastack
while true; do
  curl -s -X POST http://llamastack.<CLUSTER_IP>.nip.io/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model": "qwen3-next-80b", "messages": [{"role": "user", "content": "test"}], "max_tokens": 10}' > /dev/null
  sleep 2
done
```

In Kiali UI:
1. Go to **Graph** tab
2. Select namespace: `catalystlab-shared`
3. Enable **Traffic Animation** (toggle in Display menu)
4. Adjust refresh interval (e.g., 15s)

You should see:
- Services as **nodes** (llamastack, vllm)
- Connections as **edges** with animated dots flowing
- Request rates (e.g., "5.0 rps") on edges
- Response times and error percentages

## Using Kiali

### Graph View (Animated Service Topology)

**Access**: Graph tab → Select namespace(s)

**Features:**
- **Traffic Animation**: Real-time dots showing request flow
- **Service Health**: Color-coded nodes (green = healthy, red = errors)
- **Edge Metrics**: Request rate, response time, error %
- **mTLS Indicators**: Padlock icons showing encrypted traffic

**Display Options:**
- **Graph Type**: Workload graph, App graph, Versioned app graph, Service graph
- **Edge Labels**: Requests/s, Response time, Throughput
- **Show**: Traffic animation, Service nodes, Security, Idle nodes

**Filters:**
- **Namespace**: Select one or more namespaces
- **Time Range**: Last 1m, 5m, 10m, etc.
- **Graph Refresh**: Auto-refresh interval

**Example Use Case:**
Visualize traffic flow from `llamastack` to `vllm` with real-time request rates:

1. Select namespace: `catalystlab-shared`
2. Enable Traffic Animation
3. Edge labels: "Request rate" + "Response time (avg)"
4. Refresh interval: 15s

### Viewing Traces from Graph

**Steps:**
1. In Graph view, click an **edge** (connection between services)
2. Side panel opens → Click **Traces** tab
3. Shows trace summaries for that service pair
4. Click **View in Tracing** to open Jaeger UI

**Important**: External URL must be configured correctly in `kiali-values.yaml`:
```yaml
external_services:
  tracing:
    external_url: "http://jaeger.<CLUSTER_IP>.nip.io"
```

### Service Health Dashboard

**Access**: Applications / Workloads / Services tabs

**Features:**
- **Health status**: Success rate, error rate, response time
- **Request volume**: Requests/s over time
- **Error breakdown**: 4xx vs 5xx errors
- **Inbound/Outbound traffic**: Per service

### Istio Config Validation

**Access**: Istio Config tab

**Features:**
- Lists all Istio resources (VirtualService, DestinationRule, Gateway, ServiceEntry, etc.)
- **Validation icons**: ✅ Valid, ⚠️ Warning, ❌ Error
- **Error details**: Click resource to see validation errors

**Example**: If you see validation errors in `kserve-lab` namespace:
```bash
# Check specific namespace
kubectl get vs,dr,se,pa -n kserve-lab
```

## Deployment Status

Use these commands to verify your deployment:

```bash
# Check Kiali deployment
kubectl get deployment -n istio-system -l app.kubernetes.io/name=kiali

# Check Kiali pod
kubectl get pods -n istio-system -l app.kubernetes.io/name=kiali

# Check Kiali service
kubectl get svc -n istio-system kiali

# Check Kiali ingress
kubectl get ingress -n istio-system kiali

# Expected resources:
# - Deployment: kiali (1/1 Running)
# - Service: kiali (ClusterIP, port 20001)
# - Ingress: kiali (hosts: kiali.<CLUSTER_IP>.nip.io)
```

### Access Information

- **Kiali UI:** `http://kiali.<CLUSTER_IP>.nip.io` (replace `<CLUSTER_IP>` with your nginx ingress external IP)
- **Jaeger UI:** `http://jaeger.<CLUSTER_IP>.nip.io` (linked from Kiali)
- **Prometheus:** `http://prometheus-stack-kube-prom-prometheus.monitoring.svc.cluster.local:9090` (internal)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Browser                                 │
│  http://kiali.<CLUSTER_IP>.nip.io                              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │   NGINX Ingress      │
              │   Controller         │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │   Kiali Service      │◄──────────────┐
              │   :20001             │               │
              └──────────┬───────────┘               │
                         │                           │
              ┌──────────┴────────────┐              │
              │                       │              │
              ▼                       ▼              │
   ┌──────────────────┐    ┌──────────────────┐     │
   │   Prometheus     │    │   Jaeger Query   │     │
   │   :9090          │    │   :16686         │     │
   └────────┬─────────┘    └──────────────────┘     │
            │                                        │
            ▼                                        │
   ┌──────────────────────────────┐                 │
   │   Istio Metrics              │                 │
   │   (from ServiceMonitor/      │                 │
   │    PodMonitor)                │                 │
   │                              │                 │
   │   - istio_requests_total     │                 │
   │   - istio_request_duration_  │                 │
   │     milliseconds              │                 │
   │   - istio_tcp_connections    │                 │
   └────────┬─────────────────────┘                 │
            │                                        │
            ▼                                        │
   ┌──────────────────────────────┐                 │
   │   Envoy Sidecars             │─────────────────┘
   │   (istio-proxy containers)   │   Istio Config
   │                              │   Queries
   │   llamastack: 2/2 ◄──┐      │
   │   (app + proxy)       │      │
   │                       │      │
   │   vllm: via           │      │
   │   ServiceEntry        │      │
   └───────────────────────┘      │
                                  │
                       Mesh Traffic
```

**Data flow:**

1. **Browser → Kiali UI**: User accesses Kiali dashboard via NGINX ingress
2. **Kiali ↔ Prometheus**: Kiali queries Prometheus for Istio metrics
   - Request rates (`istio_requests_total`)
   - Latencies (`istio_request_duration_milliseconds`)
   - TCP connections, error rates, etc.
3. **Kiali ↔ Istio API**: Kiali queries Kubernetes/Istio APIs for:
   - Service discovery
   - Istio configuration (VirtualService, DestinationRule, etc.)
   - Health status
4. **Kiali → Jaeger**: User clicks "View in Tracing" → Browser redirects to Jaeger external URL
5. **Envoy Sidecars → Prometheus**: Istio sidecars expose metrics, scraped by Prometheus via PodMonitor

**Key Integrations:**
- **Prometheus**: Provides real-time traffic metrics for animated graph
- **Jaeger**: Provides distributed trace correlation
- **Istio**: Provides service mesh telemetry and configuration

## Troubleshooting

### Kiali UI Not Accessible

**Test connectivity:**

```bash
curl -I http://kiali.<CLUSTER_IP>.nip.io
```

**Common issues:**

1. **Ingress not configured**: Verify ingress exists
   ```bash
   kubectl get ingress -n istio-system kiali
   kubectl describe ingress -n istio-system kiali
   ```

2. **Kiali pod not running**: Check pod status
   ```bash
   kubectl get pods -n istio-system -l app.kubernetes.io/name=kiali
   kubectl logs -n istio-system -l app.kubernetes.io/name=kiali
   ```

3. **NGINX ingress not working**: Verify ingress controller
   ```bash
   kubectl get pods -n ingress-nginx
   kubectl get svc -n ingress-nginx
   ```

4. **DNS resolution**: nip.io requires internet access
   - Try direct IP: `curl http://<CLUSTER_IP>`
   - Check DNS: `nslookup kiali.<CLUSTER_IP>.nip.io`

### Graph Shows No Traffic

**Symptom**: Kiali Graph view shows "Empty Graph" or "No Graph Data"

**Possible Causes & Fixes:**

#### 1. No Traffic Flowing

**Check**: Are applications sending requests?

```bash
# Generate test traffic
curl -X POST http://llamastack.<CLUSTER_IP>.nip.io/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen3-next-80b", "messages": [{"role": "user", "content": "test"}], "max_tokens": 10}'
```

#### 2. Sidecars Not Injected

**Check**: Verify pods have istio-proxy sidecar

```bash
kubectl get pods -n catalystlab-shared
```

Expected: `2/2` containers (app + istio-proxy)

**Fix**: Enable sidecar injection
```bash
kubectl label namespace catalystlab-shared istio-injection=enabled --overwrite
kubectl rollout restart deployment -n catalystlab-shared
```

#### 3. Prometheus Not Scraping Istio Metrics

**Check**: Query Prometheus for Istio metrics

```bash
kubectl exec -n monitoring prometheus-stack-kube-prom-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=istio_requests_total" | jq ".data.result | length"
```

Should return > 0.

**Fix**: Apply Istio ServiceMonitor/PodMonitor
```bash
kubectl apply -f ../istio/servicemonitor.yaml
```

#### 4. Kiali Can't Reach Prometheus

**Check**: Test connection from Kiali pod

```bash
kubectl exec -n istio-system -l app.kubernetes.io/name=kiali -- \
  curl -I http://prometheus-stack-kube-prom-prometheus.monitoring.svc.cluster.local:9090
```

Expected: `HTTP 200 OK`

**Fix**: Verify `kiali-values.yaml` prometheus URL is correct
```yaml
external_services:
  prometheus:
    url: "http://prometheus-stack-kube-prom-prometheus.monitoring.svc.cluster.local:9090"
```

#### 5. Namespace Not Selected

**Check**: In Kiali UI, verify namespace is selected in dropdown

**Fix**: Select the namespace containing your services (e.g., `catalystlab-shared`)

### Service Not Appearing in Graph

**Symptom**: llamastack shows up, but vllm is missing

**Possible Causes:**

#### 1. Service in Different Namespace

**Check**: vllm might be in `kserve-lab` namespace

**Fix**: Create ServiceEntry to register external service
```bash
kubectl apply -f ../istio/vllm-serviceentry.yaml
```

Or select multiple namespaces in Kiali UI Graph view.

#### 2. Service Not in Mesh

**Check**: Does the service have an istio-proxy sidecar?

```bash
kubectl get pods -n kserve-lab
```

**Note**: KServe services may not be compatible with Istio sidecars. Use ServiceEntry instead.

#### 3. No Traffic Between Services

**Check**: Generate traffic that calls the missing service

```bash
# Traffic must flow through monitored services
curl http://llamastack.<CLUSTER_IP>.nip.io/...  # This calls vllm internally
```

### Jaeger Link Not Working

**Symptom**: "View in Tracing" button doesn't open Jaeger or shows 404

**Possible Causes:**

#### 1. Incorrect External URL

**Check**: Verify `kiali-values.yaml` external URL

```yaml
external_services:
  tracing:
    external_url: "http://jaeger.<CLUSTER_IP>.nip.io"  # Must match actual ingress
```

**Fix**: Update ConfigMap and restart Kiali
```bash
kubectl edit configmap kiali -n istio-system
# Update external_services.tracing.external_url
kubectl rollout restart deployment kiali -n istio-system
```

#### 2. Jaeger Not Accessible

**Check**: Can browser access Jaeger directly?

```bash
curl -I http://jaeger.<CLUSTER_IP>.nip.io
```

**Fix**: Verify Jaeger ingress is configured (see `../jaeger/README.md`)

#### 3. CORS Issues

**Check**: Browser console for CORS errors

**Fix**: Jaeger should allow cross-origin requests from Kiali domain

### Istio Config Errors

**Symptom**: Kiali shows validation errors in Istio Config tab

**Example**: Errors in `kserve-lab` namespace

**Check**: View specific errors

```bash
kubectl get vs,dr,se,pa -n kserve-lab
```

**Common Issues:**

1. **Failed pods with Istio annotations**: Delete failed pods
   ```bash
   kubectl delete pod <pod-name> -n kserve-lab
   ```

2. **Namespace incorrectly labeled for injection**: Disable injection for incompatible namespaces
   ```bash
   kubectl label namespace kserve-lab istio-injection=disabled --overwrite
   ```

3. **Invalid Istio resources**: Use `kubectl describe` to see validation errors
   ```bash
   kubectl describe virtualservice <name> -n <namespace>
   ```

### Performance Issues

**Symptom**: Kiali UI slow to load, graph takes long to render

**Common Causes:**

1. **Too many services**: Reduce scope by selecting specific namespaces
2. **Short refresh interval**: Increase graph refresh interval (e.g., 30s → 60s)
3. **Resource constraints**: Check Kiali pod resources

```bash
kubectl top pod -n istio-system -l app.kubernetes.io/name=kiali
kubectl describe pod -n istio-system -l app.kubernetes.io/name=kiali
```

**Fix**: Increase Kiali resource limits in `kiali-values.yaml`:
```yaml
deployment:
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 1000m
      memory: 2Gi
```

### Kiali Logs

**View Kiali logs:**

```bash
kubectl logs -n istio-system -l app.kubernetes.io/name=kiali --tail=100
```

**Common errors:**

- `Failed to connect to Prometheus`: Check Prometheus URL and connectivity
- `Failed to query Istio config`: Check RBAC permissions
- `Jaeger unreachable`: Check Jaeger in-cluster URL

## Security Considerations

> ⚠️ **CRITICAL**: This deployment has significant security limitations. Read carefully before deploying.

### Current Security Posture

**❌ Missing Security Controls:**

1. **No Authentication**
   - Kiali UI accessible without login (`strategy: anonymous`)
   - Anyone with network access can view all service topology
   - **Risk**: Unauthorized access to infrastructure details, service dependencies, performance data

2. **No TLS/HTTPS**
   - All communication over HTTP (plaintext)
   - Data transmitted unencrypted between browser and Kiali
   - **Risk**: Man-in-the-middle attacks, data interception

3. **No RBAC**
   - No role-based access control
   - Cannot restrict view to specific namespaces per user
   - **Risk**: Excessive information exposure

4. **No Network Policies**
   - Kiali can query all cluster APIs
   - **Risk**: Lateral movement in case of compromise

5. **No Audit Logging**
   - No record of who accessed Kiali or what actions were performed
   - **Risk**: Cannot detect or investigate security incidents

### Acceptable Use

**This deployment is acceptable for:**
- Lab/development environments
- Internal testing with non-sensitive infrastructure
- Temporary troubleshooting sessions
- Proof-of-concept deployments
- Learning Istio and service mesh concepts

**This deployment is NOT acceptable for:**
- Production environments
- Environments with sensitive services or data
- Compliance-regulated workloads (HIPAA, SOC 2, PCI-DSS)
- Multi-tenant environments
- Publicly accessible clusters

### Security Enhancement Roadmap

**Minimum (Development):**
1. Implement basic auth on ingress
2. Restrict ingress to specific IP ranges
3. Add network policies
4. Enable audit logging

**Recommended (Staging):**
1. Enable TLS/HTTPS via cert-manager
2. Implement OAuth2 proxy with SSO
3. Enable RBAC with namespace restrictions
4. Implement request rate limiting
5. Add security headers

**Required (Production):**
1. Full OAuth2/OIDC integration (Keycloak, Okta, Auth0)
2. TLS everywhere (ingress + inter-service)
3. Fine-grained RBAC policies
4. Network policies (deny-all default)
5. Pod security policies/admission controllers
6. Regular security audits
7. Automated vulnerability scanning
8. Compliance controls (data retention, GDPR, etc.)
9. Multi-factor authentication (MFA)
10. Security Information and Event Management (SIEM) integration

### Quick Security Improvements

**Add Basic Auth (5 minutes):**

```bash
# Create basic auth secret
htpasswd -c auth kiali-admin
kubectl create secret generic kiali-basic-auth --from-file=auth -n istio-system

# Update ingress.yaml annotations:
annotations:
  nginx.ingress.kubernetes.io/auth-type: basic
  nginx.ingress.kubernetes.io/auth-secret: kiali-basic-auth
  nginx.ingress.kubernetes.io/auth-realm: "Kiali - Authentication Required"
```

**Restrict Access to IP Range (2 minutes):**

```bash
# Update ingress.yaml annotations:
annotations:
  nginx.ingress.kubernetes.io/whitelist-source-range: "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
```

**Enable OAuth2 with Kiali (Recommended):**

Update `kiali-values.yaml`:

```yaml
auth:
  strategy: openid
  openid:
    client_id: "kiali"
    issuer_uri: "https://your-oidc-provider.com"
    # Additional OIDC configuration
```

Redeploy Kiali:
```bash
helm upgrade kiali-server kiali/kiali-server \
  -n istio-system \
  -f kiali/kiali-values.yaml
```

**Add TLS/HTTPS (with cert-manager):**

```bash
# Install cert-manager first
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# Update ingress.yaml:
annotations:
  cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  tls:
    - hosts:
        - kiali.<CLUSTER_IP>.nip.io
      secretName: kiali-tls
```

## Uninstalling Kiali

Kiali can be removed without affecting Istio or other observability tools.

### Step 1: Remove Ingress

```bash
kubectl delete -f kiali/ingress.yaml
```

### Step 2: Uninstall Helm Release

```bash
helm uninstall kiali-server -n istio-system
```

### Step 3: Cleanup ConfigMaps and Secrets (if any remain)

```bash
kubectl delete configmap -n istio-system kiali
kubectl delete secret -n istio-system kiali
```

### Verify Cleanup

```bash
kubectl get all -n istio-system -l app.kubernetes.io/name=kiali
kubectl get ingress -n istio-system kiali
```

All should return "No resources found" or empty results.

**Note**: Istio, Prometheus, and Jaeger continue to function normally after Kiali removal. Only the service topology visualization is lost.

## References

- [Kiali Documentation](https://kiali.io/docs/)
- [Kiali Helm Chart](https://github.com/kiali/helm-charts)
- [Istio + Kiali Integration](https://istio.io/latest/docs/tasks/observability/kiali/)
- [Kiali Graph Features](https://kiali.io/docs/features/topology/)
- [Kiali Security](https://kiali.io/docs/configuration/authentication/)
- [Prometheus Integration](https://kiali.io/docs/configuration/p8s-jaeger-grafana/)
