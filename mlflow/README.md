# MLflow Deployment on Kubernetes

> 📝 **CONFIGURATION NOTE**: This README uses placeholders for environment-specific values. Before deployment, update `ingress.yaml` with your cluster's external IP. Replace `<CLUSTER_IP>` in examples with your nginx ingress external IP.

Deploy MLflow as an LLM trace viewer and experiment tracking system in the `catalystlab-shared` namespace. This deployment uses CNPG PostgreSQL for metadata storage and integrates with OpenTelemetry for distributed trace collection from LLaMA Stack inference pipelines.

**Target cluster:** `<CLUSTER_IP>`
**Namespace:** `catalystlab-shared`

## Prerequisites

Before deploying MLflow, verify that the following components are available on your Kubernetes cluster.

### Verification Commands

Run these commands against your cluster to verify prerequisites:

```bash
# Check CNPG PostgreSQL cluster
kubectl get clusters.postgresql.cnpg.io -n catalystlab-shared

# Check pgvector-cluster pods
kubectl get pods -n catalystlab-shared -l cnpg.io/cluster=pgvector-cluster

# Verify PostgreSQL secret exists
kubectl get secret -n catalystlab-shared pgvector-cluster-app

# Check Nginx Ingress Controller
kubectl get ingressclass
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx

# Check storage classes
kubectl get storageclass

# Verify LLaMA Stack deployment
kubectl get deployments -n catalystlab-shared
kubectl get pods -n catalystlab-shared
```

### Expected Results

#### 1. CNPG PostgreSQL Cluster

**Status:**
```
NAME               AGE   INSTANCES   READY   STATUS                     PRIMARY
pgvector-cluster   12h   1           1       Cluster in healthy state   pgvector-cluster-1
```

**Pod:**
```
NAME                 READY   STATUS    RESTARTS   AGE
pgvector-cluster-1   1/1     Running   0          12h
```

**Service endpoints:**
- `pgvector-cluster-rw` (read-write): Primary endpoint for MLflow
- `pgvector-cluster-ro` (read-only): Available for read operations
- `pgvector-cluster-r` (read): Available for read operations

**Existing databases:**
```bash
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- psql -U postgres -c '\l'
```

Expected databases:
- `llamastack` (owner: vectordb)
- `vectordb` (owner: vectordb)
- **Note**: `mlflow` database must be created before deployment

#### 2. PostgreSQL Secret

**Secret name:** `pgvector-cluster-app`

Required keys:
- `username` ✅
- `password` ✅

Verify keys exist:
```bash
kubectl get secret -n catalystlab-shared pgvector-cluster-app \
  -o jsonpath='{.data}' | jq 'keys'
```

Expected output includes `username` and `password` among other connection details.

#### 3. Nginx Ingress Controller

**IngressClass:**
```
NAME    CONTROLLER             PARAMETERS   AGE
nginx   k8s.io/ingress-nginx   <none>       34d
```

**Controller pod:**
```
NAME                                       READY   STATUS    RESTARTS   AGE
ingress-nginx-controller-78c9c55db-zhbtr   1/1     Running   0          24d
```

**Service with external IP:**
```
NAME                       TYPE           EXTERNAL-IP      PORT(S)
ingress-nginx-controller   LoadBalancer   <CLUSTER_IP>   80:31123/TCP,443:31755/TCP
```

**External IP:** `<CLUSTER_IP>` - Used for constructing the MLflow ingress hostname.

#### 4. Storage Provisioner

**Available storage classes:**
```
NAME                   PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE
local-path (default)   rancher.io/local-path   Delete          WaitForFirstConsumer
openebs-hostpath       openebs.io/local        Delete          WaitForFirstConsumer
openebs-lvmpv          local.csi.openebs.io    Delete          Immediate
```

MLflow will use the `local-path` storage class for artifact storage.

**Existing PVCs in catalystlab-shared:**
```
NAME                 STATUS   VOLUME       CAPACITY   STORAGECLASS
llamastack-pvc       Bound    pvc-bdfd...  10Gi       local-path
pgvector-cluster-1   Bound    pvc-cf32...  20Gi       local-path
```

#### 5. LLaMA Stack Deployment

**Deployment:**
```
NAME         READY   UP-TO-DATE   AVAILABLE   AGE
llamastack   1/1     1            1           11h
```

**Pod:**
```
NAME                         READY   STATUS    RESTARTS   AGE
llamastack-9ffb4584c-scswr   1/1     Running   0          11h
```

**Service:**
```
NAME         TYPE        CLUSTER-IP      PORT(S)
llamastack   ClusterIP   10.x.x.x        8321/TCP
```

LLaMA Stack will send OpenTelemetry traces to the OTel Collector, which forwards them to MLflow's `/v1/traces` endpoint.

#### 6. OpenTelemetry Collector

**Status:** Not deployed yet (will be deployed after MLflow)

## Prerequisites Summary

| Component | Status | Details |
|-----------|--------|---------|
| CNPG PostgreSQL Cluster | ✅ Ready | `pgvector-cluster` healthy with 1/1 instances |
| PostgreSQL Secret | ✅ Ready | `pgvector-cluster-app` contains credentials |
| Nginx Ingress | ✅ Ready | External IP: `<CLUSTER_IP>` |
| Storage Provisioner | ✅ Ready | `local-path` storage class available |
| LLaMA Stack | ✅ Ready | Deployment running with service on port 8321 |
| OTel Collector | ⚪ Pending | To be deployed after MLflow |

## Pre-Deployment Action

Before deploying MLflow, create the `mlflow` database in PostgreSQL:

```bash
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U postgres -c "CREATE DATABASE mlflow OWNER vectordb;"
```

Verify the database was created:

```bash
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U postgres -c '\l' | grep mlflow
```

## Deployment

### Step 1: Deploy PVC for Artifacts

```bash
kubectl apply -f pvc.yaml
```

Verify the PVC was created:

```bash
kubectl get pvc -n catalystlab-shared mlflow-artifacts-pvc
```

Expected status: `Pending` (will bind when pod is created)

### Step 2: Deploy MLflow Deployment

```bash
kubectl apply -f deployment.yaml
```

Monitor the deployment:

```bash
kubectl get pods -n catalystlab-shared -l app=mlflow -w
```

Wait for the pod to reach `Running` status.

Check logs for any errors:

```bash
kubectl logs -n catalystlab-shared -l app=mlflow --tail=50
```

### Step 3: Deploy MLflow Service

```bash
kubectl apply -f service.yaml
```

Verify the service:

```bash
kubectl get svc -n catalystlab-shared mlflow
```

Expected output:
```
NAME     TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)    AGE
mlflow   ClusterIP   10.x.x.x       <none>        5000/TCP   ...
```

### Step 4: Deploy MLflow Ingress

```bash
kubectl apply -f ingress.yaml
```

Verify the ingress:

```bash
kubectl get ingress -n catalystlab-shared mlflow
```

Expected output should show the hostname `mlflow.<CLUSTER_IP>.nip.io`.

## Verification

### 1. Health Check (Basic)

**Note:** The `/health` endpoint passes even with broken `--allowed-hosts`, so don't rely on this alone.

```bash
curl http://mlflow.<CLUSTER_IP>.nip.io/health
```

Expected: `OK`

### 2. API Access Test (Real Verification)

This is the **real test** — it will return 403 if `--allowed-hosts` is configured incorrectly:

```bash
curl -X POST http://mlflow.<CLUSTER_IP>.nip.io/api/2.0/mlflow/experiments/search \
  -H 'Content-Type: application/json' -d '{}'
```

Expected: JSON response with empty experiments list (NOT 403)

```json
{"experiments": []}
```

If you get `403 Forbidden` with "DNS rebinding" error, check the `--allowed-hosts` configuration in [deployment.yaml](deployment.yaml).

### 3. Access MLflow UI

Open in browser:

```
http://mlflow.<CLUSTER_IP>.nip.io
```

You should see the MLflow UI with no experiments yet.

## Post-Deployment: OTel Trace Collection

After MLflow is running and verified, set up trace collection:

### 1. Create Initial Experiment

Create an experiment for LLaMA Stack traces:

```bash
curl -X POST http://mlflow.<CLUSTER_IP>.nip.io/api/2.0/mlflow/experiments/create \
  -H 'Content-Type: application/json' \
  -d '{"name": "llamastack-traces"}'
```

**Capture the experiment ID from the response:**

```json
{"experiment_id": "1"}
```

### 2. Update OTel Collector Config

Edit [otel-collector-config.yaml](otel-collector-config.yaml) and replace the placeholder experiment ID:

```yaml
headers:
  x-mlflow-experiment-id: "1"  # Replace with actual ID from step 1
```

### 3. Deploy OTel Collector

```bash
kubectl apply -f otel-collector-config.yaml
kubectl apply -f otel-collector.yaml
```

Verify the OTel Collector is running:

```bash
kubectl get pods -n catalystlab-shared -l app=otel-collector
```

Check logs:

```bash
kubectl logs -n catalystlab-shared -l app=otel-collector --tail=50
```

### 4. Verify LLaMA Stack OTel Configuration

Check that LLaMA Stack is configured to send traces to the OTel Collector:

```bash
kubectl get deployment llamastack -n catalystlab-shared -o yaml | grep OTEL
```

Expected environment variable:
```yaml
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.catalystlab-shared.svc.cluster.local:4317
```

If not configured, update the LLaMA Stack deployment to include this environment variable.

### 5. Verify Traces are Landing

Trigger some inference requests through LLaMA Stack, then check the MLflow UI:

1. Go to: `http://mlflow.<CLUSTER_IP>.nip.io`
2. Click on **Experiments** → **llamastack-traces**
3. Click on the **Traces** tab
4. You should see traces appearing with span details

## Deployment Verification

Use these commands to verify your deployment:

```bash
# Check MLflow components
kubectl get pods,svc,pvc,ingress -n catalystlab-shared -l app=mlflow

# Check OTel Collector
kubectl get pods,svc -n catalystlab-shared -l app=otel-collector

# Verify database
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U postgres -c '\l' | grep mlflow

# Expected resources:
# - Database: mlflow (PostgreSQL)
# - PVC: mlflow-artifacts-pvc (Bound, 10Gi)
# - Deployment: mlflow (1/1 Running)
# - Service: mlflow (ClusterIP, port 5000)
# - Ingress: mlflow (hosts: mlflow.<CLUSTER_IP>.nip.io)
# - OTel Collector: otel-collector (1/1 Running, ports 4317,4318)
```

### Access Information

- **MLflow UI:** `http://mlflow.<CLUSTER_IP>.nip.io` (replace `<CLUSTER_IP>` with your nginx ingress external IP)
- **MLflow API:** `http://mlflow.<CLUSTER_IP>.nip.io/api/2.0/mlflow/`
- **OTel Collector (internal):** `http://otel-collector.catalystlab-shared.svc.cluster.local:4317`

## Troubleshooting

### Pod Not Starting

Check pod events:

```bash
kubectl describe pod -n catalystlab-shared -l app=mlflow
```

Common issues:
- PVC not binding (check storage provisioner)
- Secret not found (verify `pgvector-cluster-app` exists)
- Image pull errors (check network/registry access)

### Database Connection Errors

Check logs for PostgreSQL connection errors:

```bash
kubectl logs -n catalystlab-shared -l app=mlflow | grep -i postgres
```

Verify the database exists:

```bash
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U postgres -c '\l' | grep mlflow
```

### 403 DNS Rebinding Errors

If API calls return 403 with "DNS rebinding" error, verify `--allowed-hosts` includes all required variants:

```bash
kubectl get deployment mlflow -n catalystlab-shared -o yaml | grep allowed-hosts
```

Should include:
```
--allowed-hosts=mlflow.<CLUSTER_IP>.nip.io,mlflow.catalystlab-shared.svc.cluster.local,mlflow.catalystlab-shared.svc.cluster.local:5000,localhost,localhost:5000
```

### Gateway API Errors

If you see store initialization errors in logs, verify `MLFLOW_TRACKING_URI` environment variable is set:

```bash
kubectl get deployment mlflow -n catalystlab-shared -o yaml | grep MLFLOW_TRACKING_URI
```

Should be set to the same value as `--backend-store-uri`.

### Traces Not Appearing

Check OTel Collector logs:

```bash
kubectl logs -n catalystlab-shared -l app=otel-collector
```

Verify the collector can reach MLflow:

```bash
kubectl exec -n catalystlab-shared -l app=otel-collector -- \
  wget -qO- http://mlflow.catalystlab-shared.svc.cluster.local:5000/health
```

Check that LLaMA Stack is sending traces:

```bash
kubectl logs -n catalystlab-shared -l app=llamastack | grep -i otel
```

## Critical Configuration Notes

### 1. DNS Rebinding Protection

MLflow 3.x uses `fnmatch` for DNS rebinding protection and **does not strip ports** from the Host header. You must include both hostname and hostname:port variants in `--allowed-hosts`.

**Incorrect:**
```
--allowed-hosts=mlflow.catalystlab-shared.svc.cluster.local
```

**Correct:**
```
--allowed-hosts=mlflow.catalystlab-shared.svc.cluster.local,mlflow.catalystlab-shared.svc.cluster.local:5000
```

### 2. MLFLOW_TRACKING_URI Environment Variable

MLflow 3.x has a bug where FastAPI gateway workers resolve the tracking store from the `MLFLOW_TRACKING_URI` environment variable, **NOT** from the `--backend-store-uri` CLI flag.

Always set both:
```yaml
command:
  - --backend-store-uri=postgresql://...
env:
  - name: MLFLOW_TRACKING_URI
    value: "postgresql://..."
```

### 3. Trace Endpoint

Use `/v1/traces` for OTLP ingestion, **NOT** `/api/2.0/mlflow/traces`.

The OTel Collector's `otlphttp` exporter automatically appends `/v1/traces` to the endpoint URL.

### 4. Experiment ID Bootstrap

The OTel Collector requires an experiment ID before it can forward traces. This creates a bootstrap sequence:

1. Deploy MLflow
2. Create experiment via API
3. Get experiment ID
4. Update OTel Collector config with ID
5. Deploy OTel Collector

## Architecture

```
LLaMA Stack ──(OTel SDK)──► OTel Collector ──(otlphttp)──► MLflow /v1/traces
  :8321                        :4317/:4318                      :5000
                                                                  │
                                          ┌───────────────────────┤
                                          ▼                       ▼
                                    PostgreSQL              PVC (artifacts)
                                   (metadata)              /mlflow/artifacts
```

**Data flow:**
1. LLaMA Stack emits OpenTelemetry spans during inference
2. OTel Collector receives spans on gRPC (4317) or HTTP (4318)
3. OTel Collector exports to MLflow's OTLP endpoint (`/v1/traces`)
4. MLflow stores trace metadata in PostgreSQL (`mlflow` database)
5. MLflow stores artifacts in PVC-backed filesystem
6. Users access traces and experiments via MLflow UI (port 5000)

## Optional: Jaeger Integration

> **Note**: Jaeger is an optional complementary tool. MLflow provides full trace functionality independently.

Jaeger can be deployed alongside MLflow to provide service graph visualization that complements MLflow's waterfall timeline views:

| Feature | MLflow | Jaeger |
|---------|--------|--------|
| Waterfall/Timeline View | ✅ Excellent | ✅ Basic |
| Service Dependency Graph | ❌ Not available | ✅ Excellent |
| Experiment Tracking | ✅ Full support | ❌ Not available |

### When to Use Each Tool

- **Use MLflow for**: Historical trace analysis, experiment tracking, waterfall views, persistent storage
- **Use Jaeger for**: Service architecture visualization, dependency analysis, troubleshooting service communication

### Architecture with Jaeger

```
LLaMA Stack → OTel Collector ─┬─► MLflow (waterfall views, experiments)
                               └─► Jaeger (service graphs, dependencies)
```

Both systems receive the same traces from the OTel Collector via fan-out configuration.

### Deployment

See [../jaeger/README.md](../jaeger/README.md) for complete Jaeger deployment instructions.

### Access URLs

- **MLflow UI**: http://mlflow.<CLUSTER_IP>.nip.io
- **Jaeger UI** (if deployed): http://jaeger.<CLUSTER_IP>.nip.io

### Security Warning

⚠️ Jaeger deployment requires security review. See [Jaeger Security Considerations](../jaeger/README.md#security-considerations) for details.

## References

- [MLflow Documentation](https://mlflow.org/docs/latest/index.html)
- [CloudNativePG Documentation](https://cloudnative-pg.io/documentation/)
- [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
- [LLaMA Stack](https://github.com/meta-llama/llama-stack)
- [Jaeger Documentation](https://www.jaegertracing.io/docs/latest/) (optional integration)
