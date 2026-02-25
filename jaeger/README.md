# Jaeger Deployment on Kubernetes (Optional)

> 📝 **CONFIGURATION NOTE**: This README uses placeholders for environment-specific values. Before deployment, update `ingress.yaml` with your cluster's external IP. Replace `<CLUSTER_IP>` in examples with your nginx ingress external IP.

> ⚠️ **OPTIONAL DEPLOYMENT**: Jaeger is a complementary tool to MLflow. MLflow provides full trace functionality independently. Deploy Jaeger only if you need service graph visualization.

> 🔒 **SECURITY WARNING**: This deployment is configured for lab/development use only. It lacks authentication, TLS/HTTPS, and RBAC. **Do NOT use in production without implementing security enhancements.** See [Security Considerations](#security-considerations) section.

Deploy Jaeger as a complementary trace visualization tool in the `catalystlab-shared` namespace. This deployment uses Badger file-based storage for trace persistence and integrates with the existing OpenTelemetry Collector to receive traces from LLaMA Stack inference pipelines.

**Target cluster:** `<CLUSTER_IP>`
**Namespace:** `catalystlab-shared`

## Why Jaeger?

Jaeger provides service graph visualization that complements MLflow's waterfall timeline views:

| Feature | MLflow | Jaeger |
|---------|--------|--------|
| Waterfall/Timeline View | ✅ Excellent | ✅ Basic |
| Service Dependency Graph | ❌ Not available | ✅ Excellent |
| Persistent Storage | ✅ PostgreSQL | ✅ Badger (file-based) |
| Experiment Tracking | ✅ Full support | ❌ Not available |
| Trace Search | ✅ Good | ✅ Excellent |
| Real-time Updates | ✅ Yes | ✅ Yes |

**Use MLflow for**: Historical trace analysis, experiment tracking, waterfall views
**Use Jaeger for**: Service architecture visualization, dependency analysis, troubleshooting service communication

## Prerequisites

Before deploying Jaeger, verify that the following components are available on your Kubernetes cluster.

### Verification Commands

Run these commands against your cluster to verify prerequisites:

```bash
# Check namespace exists
kubectl get namespace catalystlab-shared

# Check Nginx Ingress Controller
kubectl get ingressclass
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx

# Check storage classes
kubectl get storageclass

# Verify MLflow deployment (Jaeger integrates with existing OTel Collector)
kubectl get deployments -n catalystlab-shared mlflow
kubectl get deployments -n catalystlab-shared otel-collector
```

### Expected Results

#### 1. Namespace

**Namespace:** `catalystlab-shared`
```
NAME                 STATUS   AGE
catalystlab-shared   Active   ...
```

#### 2. Nginx Ingress Controller

**IngressClass:**
```
NAME    CONTROLLER             PARAMETERS   AGE
nginx   k8s.io/ingress-nginx   <none>       34d
```

**Service with external IP:**
```
NAME                       TYPE           EXTERNAL-IP      PORT(S)
ingress-nginx-controller   LoadBalancer   <CLUSTER_IP>   80:31123/TCP,443:31755/TCP
```

**External IP:** `<CLUSTER_IP>` - Used for constructing the Jaeger ingress hostname.

#### 3. Storage Provisioner

**Available storage classes:**
```
NAME                   PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE
local-path (default)   rancher.io/local-path   Delete          WaitForFirstConsumer
```

Jaeger will use the `local-path` storage class for Badger storage.

#### 4. MLflow and OTel Collector

**Deployments:**
```
NAME             READY   UP-TO-DATE   AVAILABLE   AGE
mlflow           1/1     1            1           ...
otel-collector   1/1     1            1           ...
```

The OTel Collector will be updated to fan-out traces to both MLflow and Jaeger.

## Prerequisites Summary

| Component | Status | Details |
|-----------|--------|---------|
| Namespace | ✅ Required | `catalystlab-shared` must exist |
| Nginx Ingress | ✅ Required | External IP: `<CLUSTER_IP>` |
| Storage Provisioner | ✅ Required | `local-path` storage class available |
| MLflow | ✅ Required | Deployment running |
| OTel Collector | ✅ Required | Deployment running, will be updated |

## Deployment

### Step 1: Deploy PVC for Badger Storage

```bash
kubectl apply -f pvc.yaml
```

Verify the PVC was created:

```bash
kubectl get pvc -n catalystlab-shared jaeger-badger-pvc
```

Expected status: `Pending` (will bind when pod is created)

### Step 2: Deploy Jaeger Deployment

```bash
kubectl apply -f deployment.yaml
```

Monitor the deployment:

```bash
kubectl get pods -n catalystlab-shared -l app=jaeger -w
```

Wait for the pod to reach `Running` status.

Check logs for any errors:

```bash
kubectl logs -n catalystlab-shared -l app=jaeger --tail=50
```

### Step 3: Deploy Jaeger Services

```bash
kubectl apply -f service.yaml
```

Verify the services:

```bash
kubectl get svc -n catalystlab-shared | grep jaeger
```

Expected output:
```
NAME               TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)                           AGE
jaeger-query       ClusterIP   10.x.x.x       <none>        16686/TCP                         ...
jaeger-collector   ClusterIP   10.x.x.x       <none>        4317/TCP,4318/TCP,14268/TCP,...  ...
```

### Step 4: Deploy Jaeger Ingress

```bash
kubectl apply -f ingress.yaml
```

Verify the ingress:

```bash
kubectl get ingress -n catalystlab-shared jaeger
```

Expected output should show the hostname `jaeger.<CLUSTER_IP>.nip.io`.

## Verification

### 1. Access Jaeger UI

Open in browser:

```
http://jaeger.<CLUSTER_IP>.nip.io
```

You should see the Jaeger UI with no traces yet (MLflow/OTel Collector integration pending).

### 2. Health Check

```bash
curl -I http://jaeger.<CLUSTER_IP>.nip.io
```

Expected: `HTTP 200 OK`

### 3. Verify Services

```bash
# Test query service (UI backend)
kubectl exec -n catalystlab-shared -l app=otel-collector -- \
  nc -zv jaeger-query.catalystlab-shared.svc.cluster.local 16686

# Test collector service (OTLP endpoint)
kubectl exec -n catalystlab-shared -l app=otel-collector -- \
  nc -zv jaeger-collector.catalystlab-shared.svc.cluster.local 4317
```

Expected: Connection succeeded for both

## Integration with OTel Collector

After Jaeger is running and verified, update the OTel Collector to send traces to both MLflow and Jaeger.

### 1. Update OTel Collector Configuration

Edit `../mlflow/otel-collector-config.yaml` and add the Jaeger exporter:

```yaml
exporters:
  otlphttp:
    endpoint: "http://mlflow.catalystlab-shared.svc.cluster.local:5000"
    headers:
      x-mlflow-experiment-id: "1"

  otlp/jaeger:
    endpoint: "http://jaeger-collector.catalystlab-shared.svc.cluster.local:4317"
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlphttp, otlp/jaeger]  # Add otlp/jaeger
```

### 2. Apply Updated Configuration

```bash
kubectl apply -f ../mlflow/otel-collector-config.yaml
kubectl rollout restart deployment/otel-collector -n catalystlab-shared
```

Wait for rollout to complete:

```bash
kubectl rollout status deployment/otel-collector -n catalystlab-shared
```

### 3. Verify Trace Flow

Check OTel Collector logs:

```bash
kubectl logs -n catalystlab-shared -l app=otel-collector --tail=50
```

Look for successful exports to both MLflow and Jaeger endpoints.

### 4. Trigger Test Traces

Send an inference request through LLaMA Stack to generate traces:

```bash
# Adjust based on your LLaMA Stack API
curl -X POST http://llamastack.catalystlab-shared.svc.cluster.local:8321/inference/chat_completion \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<model-name>",
    "messages": [{"role": "user", "content": "Hello, test trace"}]
  }'
```

Wait 5-10 seconds for trace propagation.

### 5. View Traces in Jaeger

1. Go to: `http://jaeger.<CLUSTER_IP>.nip.io`
2. Select **Service** dropdown (should show `llamastack` or similar)
3. Click **Find Traces**
4. You should see traces with service graph visualization

## Deployment Status

Use these commands to verify your deployment:

```bash
# Check all components
kubectl get pods,svc,pvc,ingress -n catalystlab-shared -l app=jaeger

# Expected resources:
# - PVC: jaeger-badger-pvc (Bound, 15Gi)
# - Deployment: jaeger (1/1 Running)
# - Service: jaeger-query (ClusterIP, port 16686)
# - Service: jaeger-collector (ClusterIP, ports 4317,4318,14268,9411)
# - Ingress: jaeger (hosts: jaeger.<CLUSTER_IP>.nip.io)
```

### Access Information

- **Jaeger UI:** `http://jaeger.<CLUSTER_IP>.nip.io` (replace `<CLUSTER_IP>` with your nginx ingress external IP)
- **MLflow UI:** `http://mlflow.<CLUSTER_IP>.nip.io` (independent, continues to work)
- **Jaeger Collector (internal):** `http://jaeger-collector.catalystlab-shared.svc.cluster.local:4317`

## Architecture

```
LLaMA Stack ──(OTel SDK)──► OTel Collector ──┬──(otlphttp)──► MLflow /v1/traces
  :8321                        :4317/:4318    │                    :5000
                                              │                      │
                                              │          ┌───────────┴────────────┐
                                              │          ▼                        ▼
                                              │    PostgreSQL                PVC (artifacts)
                                              │   (metadata)                /mlflow/artifacts
                                              │
                                              └──(otlp/jaeger)──► Jaeger Collector
                                                                       :4317
                                                                         │
                                                                         ▼
                                                                   Badger Storage
                                                                   (PVC /badger)
```

**Data flow:**
1. LLaMA Stack emits OpenTelemetry spans during inference
2. OTel Collector receives spans on gRPC (4317) or HTTP (4318)
3. OTel Collector **fans out** to both:
   - MLflow's OTLP endpoint (`/v1/traces`) → PostgreSQL + PVC
   - Jaeger's OTLP endpoint (4317) → Badger file storage
4. Users access:
   - MLflow UI for waterfall views and experiment tracking
   - Jaeger UI for service graphs and dependency analysis

## Troubleshooting

### Pod Not Starting

Check pod events:

```bash
kubectl describe pod -n catalystlab-shared -l app=jaeger
```

Common issues:
- PVC not binding (check storage provisioner)
- Image pull errors (check network/registry access)
- Resource constraints (check node capacity)

### PVC Stuck in Pending

Check PVC status:

```bash
kubectl describe pvc -n catalystlab-shared jaeger-badger-pvc
```

Common issues:
- Storage class not available
- No available nodes with capacity
- WaitForFirstConsumer binding mode (normal until pod starts)

### UI Not Accessible

Verify ingress:

```bash
kubectl get ingress -n catalystlab-shared jaeger
kubectl describe ingress -n catalystlab-shared jaeger
```

Test connectivity:

```bash
curl -I http://jaeger.<CLUSTER_IP>.nip.io
```

Common issues:
- Ingress controller not running
- DNS not resolving (nip.io requires internet access)
- Pod not ready (check pod status)

### Traces Not Appearing

**If no traces in Jaeger but MLflow shows traces:**

1. Check OTel Collector configuration:
```bash
kubectl get configmap -n catalystlab-shared otel-collector-config -o yaml
```

Verify `otlp/jaeger` exporter is configured and included in pipeline.

2. Check OTel Collector logs:
```bash
kubectl logs -n catalystlab-shared -l app=otel-collector | grep -i jaeger
```

Look for export errors.

3. Verify Jaeger collector endpoint:
```bash
kubectl exec -n catalystlab-shared -l app=otel-collector -- \
  nc -zv jaeger-collector.catalystlab-shared.svc.cluster.local 4317
```

4. Check Jaeger logs:
```bash
kubectl logs -n catalystlab-shared -l app=jaeger --tail=100
```

Look for incoming spans or errors.

**If no traces in both Jaeger and MLflow:**
- Issue is upstream (LLaMA Stack or OTel Collector receiver)
- Check LLaMA Stack OTel configuration
- Verify OTel Collector receiver is working

### Storage Issues

Check Badger storage health:

```bash
kubectl exec -n catalystlab-shared -l app=jaeger -- ls -lah /badger
```

Check PVC capacity:

```bash
kubectl get pvc -n catalystlab-shared jaeger-badger-pvc
```

If storage is full, consider:
- Increasing PVC size
- Implementing trace sampling
- Adjusting Badger retention settings

## Security Considerations

> ⚠️ **CRITICAL**: This deployment has significant security limitations. Read carefully before deploying.

### Current Security Posture

**❌ Missing Security Controls:**

1. **No Authentication**
   - Jaeger UI accessible without login
   - Anyone with network access can view all traces
   - **Risk**: Unauthorized access to sensitive trace data (prompts, responses, API keys)

2. **No TLS/HTTPS**
   - All communication over HTTP (plaintext)
   - Data transmitted unencrypted
   - **Risk**: Man-in-the-middle attacks, data interception

3. **No RBAC**
   - No role-based access control
   - Cannot restrict trace visibility by user/team
   - **Risk**: Excessive data exposure

4. **No Network Policies**
   - Pod can communicate with all cluster resources
   - **Risk**: Lateral movement in case of compromise

### Acceptable Use

**This deployment is acceptable for:**
- Lab/development environments
- Internal testing with non-sensitive data
- Temporary troubleshooting sessions
- Proof-of-concept deployments

**This deployment is NOT acceptable for:**
- Production environments
- Environments with sensitive data (PII, API keys, business logic)
- Compliance-regulated workloads (HIPAA, SOC 2, PCI-DSS)
- Multi-tenant environments without network isolation

### Security Enhancement Roadmap

**Minimum (Development):**
1. Implement basic auth on ingress
2. Restrict ingress to specific IP ranges
3. Add network policies

**Recommended (Staging):**
1. Enable TLS/HTTPS via cert-manager
2. Implement OAuth2 proxy with SSO
3. Enable audit logging
4. Implement trace sampling/filtering

**Required (Production):**
1. Full OAuth2/OIDC integration
2. TLS everywhere (ingress + inter-service)
3. RBAC with fine-grained permissions
4. Network policies (deny-all default)
5. Pod security policies/admission controllers
6. Regular security audits
7. Encrypted storage (encryption at rest)
8. Compliance controls (data retention, GDPR, etc.)

### Quick Security Improvements

**Add Basic Auth (5 minutes):**

```bash
# Create basic auth secret
htpasswd -c auth jaeger-admin
kubectl create secret generic jaeger-basic-auth --from-file=auth -n catalystlab-shared

# Update ingress.yaml annotations:
annotations:
  nginx.ingress.kubernetes.io/auth-type: basic
  nginx.ingress.kubernetes.io/auth-secret: jaeger-basic-auth
  nginx.ingress.kubernetes.io/auth-realm: "Jaeger UI - Authentication Required"
```

**Restrict Access to IP Range (2 minutes):**

```bash
# Update ingress.yaml annotations:
annotations:
  nginx.ingress.kubernetes.io/whitelist-source-range: "<YOUR_IP_RANGES>"
```

## Uninstalling Jaeger

Jaeger can be removed without affecting MLflow functionality.

### Step 1: Remove OTel Collector Integration

Edit `../mlflow/otel-collector-config.yaml` and remove Jaeger exporter:

```yaml
# Remove otlp/jaeger from exporters section
# Change pipeline back to:
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlphttp]  # Remove otlp/jaeger
```

Apply and restart:

```bash
kubectl apply -f ../mlflow/otel-collector-config.yaml
kubectl rollout restart deployment/otel-collector -n catalystlab-shared
```

### Step 2: Delete Jaeger Resources

```bash
kubectl delete -f ingress.yaml
kubectl delete -f service.yaml
kubectl delete -f deployment.yaml
kubectl delete -f pvc.yaml
```

**Note**: Deleting the PVC will permanently delete all stored traces. If you want to preserve traces, backup the PVC first.

### Verify Cleanup

```bash
kubectl get pods -n catalystlab-shared -l app=jaeger
kubectl get svc -n catalystlab-shared | grep jaeger
kubectl get pvc -n catalystlab-shared jaeger-badger-pvc
```

All should return "No resources found" or empty results.

MLflow continues to function normally after Jaeger removal.

## References

- [Jaeger Documentation](https://www.jaegertracing.io/docs/latest/)
- [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
- [Jaeger Badger Storage](https://www.jaegertracing.io/docs/latest/deployment/#badger---local-storage)
- [MLflow Tracing](https://mlflow.org/docs/latest/llm-tracking.html)
