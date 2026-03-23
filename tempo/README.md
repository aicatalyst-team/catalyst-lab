# Grafana Tempo - Distributed Tracing Backend

> 📝 **CONFIGURATION NOTE**: This README uses placeholders for environment-specific values. Before deployment, update `ingress.yaml` and `kiali-tempo-patch.yaml` with your cluster's external IP. Replace `<CLUSTER_IP>` in examples with your nginx ingress external IP.

> 🔄 **MIGRATION FROM JAEGER**: Tempo replaces Jaeger as the distributed tracing backend. Jaeger was removed on March 12, 2026. This deployment maintains compatibility with existing MLflow integration while adding better scalability and Grafana integration.

> 🔒 **SECURITY WARNING**: This deployment is configured for lab/development use only. It lacks authentication, TLS/HTTPS, and RBAC. **Do NOT use in production without implementing security enhancements.** See [Security Considerations](#security-considerations) section.

Tempo is a high-scale distributed tracing backend that replaces Jaeger in the catalyst-lab observability stack. It provides trace storage and querying for LlamaStack, Kagent agents, and other instrumented services.

**Target cluster:** `root@<CLUSTER_IP>`
**Namespace:** `catalystlab-shared`

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Instrumented Services                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ LlamaStack   │  │ Kagent Agents│  │ Other Apps   │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
└─────────┼──────────────────┼──────────────────┼──────────────────┘
          │                  │                  │
          └──────────────────┴──────────────────┘
                             │
                    ┌────────▼────────┐
                    │  OTel Collector │
                    │  (processors)   │
                    └────────┬────────┘
                             │
          ┌──────────────────┴──────────────────┐
          │                                     │
    ┌─────▼─────┐                      ┌───────▼───────┐
    │  MLflow   │                      │     Tempo     │
    │ (traces + │                      │ (distributed  │
    │ metadata) │                      │    traces)    │
    └───────────┘                      └───────┬───────┘
                                               │
                             ┌─────────────────┴─────────────────┐
                             │                                   │
                    ┌────────▼────────┐              ┌──────────▼──────────┐
                    │     Kiali       │              │      Grafana        │
                    │ (service mesh   │              │  (trace analysis)   │
                    │  visualization) │              │                     │
                    └─────────────────┘              └─────────────────────┘
```

## Why Tempo?

**Replaced**: Jaeger (removed March 12, 2026)

**Advantages over Jaeger**:
- **Better scalability**: Object storage backend (S3/GCS) vs local disk
- **Lower cost**: Uses cheap object storage, no expensive indexes
- **Grafana integration**: Native Grafana datasource for advanced visualization
- **Simpler operations**: Fewer moving parts in distributed mode
- **TraceQL**: Powerful query language for trace analysis

**Trade-offs**:
- No built-in UI (use Grafana or Kiali)
- Query performance depends on object storage
- Requires external datasource for visualization

## Components

### Tempo Distributed Architecture

1. **Distributor** (receives traces)
   - Listens on OTLP gRPC (4317) and HTTP (4318)
   - Also supports Jaeger, Zipkin protocols
   - Load balances across ingesters

2. **Ingester** (writes traces)
   - Buffers traces in memory
   - Writes to persistent storage
   - Uses WAL for durability

3. **Query Frontend** (serves queries)
   - Handles query requests from Kiali/Grafana
   - Parallelizes queries across queriers
   - Caches results

4. **Querier** (executes queries)
   - Reads from object storage
   - Searches traces by ID or attributes
   - Returns results to query frontend

5. **Compactor** (maintenance)
   - Compacts trace blocks
   - Implements retention policies
   - Reduces storage costs

6. **Gateway** (optional)
   - Single entry point for all operations
   - Load balancing and routing

## Installation

### Prerequisites

- Kubernetes cluster with kubectl access
- Helm 3.x installed
- `local-path` StorageClass available (for PVCs)
- At least 2GB memory available on worker nodes

### Deployment Steps

```bash
# 1. Add Grafana Helm repository
ssh root@<CLUSTER_IP> 'helm repo add grafana https://grafana.github.io/helm-charts && helm repo update'

# 2. Copy Helm values to cluster
scp tempo-minimal-values.yaml root@<CLUSTER_IP>:/tmp/

# 3. Install Tempo
ssh root@<CLUSTER_IP> 'helm install tempo grafana/tempo-distributed \
  -n catalystlab-shared \
  -f /tmp/tempo-minimal-values.yaml'

# 4. Disable Istio sidecar injection for Tempo components
# IMPORTANT: Istio sidecars interfere with Tempo's gRPC communication
ssh root@<CLUSTER_IP> 'kubectl get deployments,statefulsets -n catalystlab-shared -l app.kubernetes.io/instance=tempo -o name | while read resource; do kubectl patch $resource -n catalystlab-shared -p '"'"'{"spec":{"template":{"metadata":{"annotations":{"sidecar.istio.io/inject":"false"}}}}}'"'"'; done'

# 5. Wait for components to start
ssh root@<CLUSTER_IP> 'kubectl get pods -n catalystlab-shared -l app.kubernetes.io/instance=tempo -w'

# Expected output (minimal deployment - some components scaled to 0 for lab environment):
# NAME                                 READY   STATUS    RESTARTS   AGE
# tempo-distributor-559c4cf459-rv7rs   1/1     Running   0          2m
# tempo-ingester-0                     1/1     Running   0          2m
# tempo-compactor-xxx-xxx              0/0     Scaled    0          2m
# tempo-gateway-xxx-xxx                0/0     Scaled    0          2m
# tempo-querier-xxx-xxx                0/0     Scaled    0          2m
# tempo-query-frontend-xxx-xxx         0/0     Scaled    0          2m
```

### Configuration

**File**: `tempo-minimal-values.yaml`

Key settings:
- **Storage**: Local filesystem (production should use S3/GCS)
- **Replication Factor**: 1 (configured for single-replica lab deployment)
- **Retention**: 7 days (configured in compactor)
- **Trace ingestion**: OTLP gRPC (4317), OTLP HTTP (4318)
- **Resources**: Minimal (suitable for lab, increase for production)
- **Multi-tenancy**: Disabled
- **Istio Sidecars**: Explicitly disabled (sidecars interfere with gRPC communication)

## Integration

### 1. OTel Collector Integration

**File**: `otel-collector-tempo.yaml`

The OTel Collector sends traces to Tempo's distributor:

```yaml
exporters:
  otlp_grpc/tempo:
    endpoint: "tempo-distributor.catalystlab-shared.svc.cluster.local:4317"
    tls:
      insecure: true

service:
  pipelines:
    traces:
      exporters: [otlp_http, otlp_grpc/tempo]  # MLflow + Tempo
```

**Important**: The gRPC endpoint does not use `http://` prefix. Using `http://` will cause connection errors.

**Apply the configuration**:
```bash
scp otel-collector-tempo.yaml root@<CLUSTER_IP>:/tmp/
ssh root@<CLUSTER_IP> 'kubectl apply -f /tmp/otel-collector-tempo.yaml'
```

### 2. Kiali Integration

**File**: `kiali-tempo-patch.yaml`

Kiali queries Tempo for trace visualization in the service mesh graph:

```yaml
external_services:
  tracing:
    enabled: true
    provider: tempo
    in_cluster_url: "http://tempo-query-frontend.catalystlab-shared.svc.cluster.local:3200"
    external_url: "http://tempo.<CLUSTER_IP>.nip.io"
    use_grpc: false
```

**Apply the patch**:
```bash
scp kiali-tempo-patch.yaml root@<CLUSTER_IP>:/tmp/
ssh root@<CLUSTER_IP> 'kubectl patch configmap kiali -n istio-system --patch-file /tmp/kiali-tempo-patch.yaml'
ssh root@<CLUSTER_IP> 'kubectl rollout restart deployment kiali -n istio-system'
```

### 3. Expose Tempo UI

**File**: `ingress.yaml`

Create NGINX ingress for external access:

```bash
scp ingress.yaml root@<CLUSTER_IP>:/tmp/
ssh root@<CLUSTER_IP> 'kubectl apply -f /tmp/ingress.yaml'
```

**Access Tempo**:
- **Internal**: `http://tempo-query-frontend.catalystlab-shared.svc.cluster.local:3200`
- **External**: `http://tempo.<CLUSTER_IP>.nip.io`

## Verification

### Check Deployment Status

```bash
# Check all Tempo pods
ssh root@<CLUSTER_IP> 'kubectl get pods -n catalystlab-shared -l app.kubernetes.io/instance=tempo'

# Check services
ssh root@<CLUSTER_IP> 'kubectl get svc -n catalystlab-shared -l app.kubernetes.io/instance=tempo'

# Check ingress
ssh root@<CLUSTER_IP> 'kubectl get ingress -n catalystlab-shared tempo'
```

### Verify Trace Flow

1. **Send a test request**:
```bash
curl -X POST http://llamastack.<CLUSTER_IP>.nip.io/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-ID: tempo-test" \
  -H "X-Session-ID: tempo-session-123" \
  -d '{
    "model": "vllm/RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8",  # pragma: allowlist secret
    "messages": [{"role": "user", "content": "Hello Tempo"}],
    "max_tokens": 10
  }'
```

2. **Check OTel Collector logs**:
```bash
ssh root@<CLUSTER_IP> 'kubectl logs -n catalystlab-shared deployment/otel-collector --tail=50 | grep tempo'
```

3. **Check Tempo distributor logs**:
```bash
ssh root@<CLUSTER_IP> 'kubectl logs -n catalystlab-shared deployment/tempo-distributor --tail=50'
```

4. **Query traces via API**:
```bash
# Port-forward to query frontend
ssh root@<CLUSTER_IP> 'kubectl port-forward -n catalystlab-shared svc/tempo-query-frontend 3200:3200' &

# Search for traces (Jaeger-compatible API)
curl -s "http://localhost:3200/api/search?service=llamastack&limit=10" | jq .

# Get specific trace by ID
curl -s "http://localhost:3200/api/traces/<trace-id>" | jq .
```

### Integration Tests

**Test Kiali → Tempo**:
1. Open Kiali: `http://kiali.<CLUSTER_IP>.nip.io`
2. Navigate to Graph → Select namespace: `catalystlab-shared`
3. Click on an edge (e.g., llamastack → vllm)
4. Click "Traces" tab
5. Should see traces with "View in Tracing" links
6. Click link → Should open Tempo UI with trace details

**Test MLflow → Tempo correlation**:
1. Open MLflow: `http://mlflow.<CLUSTER_IP>.nip.io`
2. View a trace in MLflow Traces tab
3. Note the trace ID
4. Query Tempo API with the same trace ID
5. Should return the same trace data

## Operations

### Scaling

**Horizontal scaling** (increase replicas):
```bash
# Scale distributors for more ingestion capacity
ssh root@<CLUSTER_IP> 'kubectl scale deployment tempo-distributor -n catalystlab-shared --replicas=2'

# Scale queriers for faster queries
ssh root@<CLUSTER_IP> 'kubectl scale deployment tempo-querier -n catalystlab-shared --replicas=2'
```

**Vertical scaling** (increase resources):
Edit `tempo-minimal-values.yaml` and update `resources` sections, then:
```bash
ssh root@<CLUSTER_IP> 'helm upgrade tempo grafana/tempo-distributed \
  -n catalystlab-shared \
  -f /tmp/tempo-minimal-values.yaml'
```

### Retention Policy

Traces are retained for **7 days** by default (configured in compactor).

**Adjust retention**:
Edit `tempo-minimal-values.yaml`:
```yaml
compactor:
  config:
    compaction:
      block_retention: 336h  # 14 days
```

Then upgrade:
```bash
ssh root@<CLUSTER_IP> 'helm upgrade tempo grafana/tempo-distributed -n catalystlab-shared -f /tmp/tempo-minimal-values.yaml'
```

### Storage Management

**Check ingester PVC usage**:
```bash
ssh root@<CLUSTER_IP> 'kubectl exec -n catalystlab-shared tempo-ingester-0 -- df -h /var/tempo'
```

**Check compactor PVC usage**:
```bash
ssh root@<CLUSTER_IP> 'kubectl exec -n catalystlab-shared deployment/tempo-compactor -- df -h /var/tempo'
```

**Expand PVC** (if running out of space):
```bash
# Edit PVC
ssh root@<CLUSTER_IP> 'kubectl edit pvc storage-tempo-ingester-0 -n catalystlab-shared'

# Change storage size (e.g., 10Gi → 20Gi)
# Save and wait for automatic expansion
```

### Monitoring

**Prometheus metrics** (ServiceMonitor enabled):
```bash
# Query Tempo metrics
ssh root@<CLUSTER_IP> 'kubectl exec -n monitoring prometheus-stack-kube-prom-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=tempo_distributor_spans_received_total" | jq .'
```

**Key metrics to monitor**:
- `tempo_distributor_spans_received_total` - Traces received
- `tempo_ingester_blocks_flushed_total` - Blocks written to storage
- `tempo_querier_spans_queried_total` - Query activity
- `tempo_compactor_blocks_deleted_total` - Compaction activity

### Logs

**View component logs**:
```bash
# Distributor (ingestion)
ssh root@<CLUSTER_IP> 'kubectl logs -n catalystlab-shared deployment/tempo-distributor -f'

# Query frontend (queries)
ssh root@<CLUSTER_IP> 'kubectl logs -n catalystlab-shared deployment/tempo-query-frontend -f'

# Ingester (storage writes)
ssh root@<CLUSTER_IP> 'kubectl logs -n catalystlab-shared tempo-ingester-0 -f'

# Compactor (maintenance)
ssh root@<CLUSTER_IP> 'kubectl logs -n catalystlab-shared deployment/tempo-compactor -f'
```

## Troubleshooting

### Issue: Too Many Unhealthy Instances in the Ring

**Symptom**:
- Grafana shows error: "too many unhealthy instances in the ring"
- Tempo queries fail with 500 errors
- Tempo distributor/querier logs: `instance X in the ring is UNHEALTHY`

**Root Cause**: Ring replication factor vs replica count mismatch causes zero redundancy. When a single pod restarts:
- With `replication_factor: 1` and `replicas: 1`: 100% of instances become unhealthy during restart
- Ring cannot achieve quorum → queries fail

**Solution - Single Node HA Configuration**:

Use `tempo-single-node-ha.yaml` for 1-worker clusters:

```bash
# Deploy with single-node HA configuration
scp tempo-single-node-ha.yaml root@<CLUSTER_IP>:/tmp/
ssh root@<CLUSTER_IP> 'helm upgrade tempo grafana/tempo-distributed \
  -n catalystlab-shared \
  -f /tmp/tempo-single-node-ha.yaml'
```

Key differences from standard deployment:
- **2 replicas** for distributor, ingester, querier, query-frontend, metrics-generator, gateway
- **replication_factor: 2** (matches replica count)
- **affinity: null** (allows multiple replicas on same node)
- **MinIO S3 storage** (required for multi-replica shared storage)
- **memcached disabled** (reduces complexity)

Trade-offs:
- ✅ Ring redundancy prevents query failures during pod restarts
- ⚠️ Multiple replicas on same node = less resilient to node failure
- ✅ Acceptable for lab environments prioritizing stability over HA

**MinIO Storage Configuration**:

```yaml
storage:
  trace:
    backend: s3
    s3:
      bucket: tempo-traces
      endpoint: minio.catalystlab-shared.svc.cluster.local:9000
      access_key: minio
      secret_key: minio123
      insecure: true
```

**Verification**:
```bash
# Check replica counts
ssh root@<CLUSTER_IP> 'kubectl get deployment,statefulset -n catalystlab-shared -l app.kubernetes.io/instance=tempo'

# Should see 2/2 replicas for ingester, distributor, etc.
# Compactor should be 1/1 (background task only)

# Verify ring health
ssh root@<CLUSTER_IP> 'kubectl logs -n catalystlab-shared deployment/tempo-distributor | grep -i ring'
```

### Issue: Istio Sidecar Interfering with Tempo

**Symptom**:
- Pods show `2/2 Running` but traces don't flow
- OTel Collector logs: `rpc error: code = Unavailable desc = no children to pick from`
- Tempo distributor logs show memberlist gossip but no trace activity

**Root Cause**: Istio sidecars intercept gRPC traffic and break Tempo's internal communication.

**Solution**:
```bash
# Disable Istio injection for all Tempo components
ssh root@<CLUSTER_IP> 'kubectl get deployments,statefulsets -n catalystlab-shared -l app.kubernetes.io/instance=tempo -o name | while read resource; do
  kubectl patch $resource -n catalystlab-shared -p '"'"'{"spec":{"template":{"metadata":{"annotations":{"sidecar.istio.io/inject":"false"}}}}}'"'"'
done'

# Verify pods restart without sidecars (should be 1/1 not 2/2)
ssh root@<CLUSTER_IP> 'kubectl get pods -n catalystlab-shared -l app.kubernetes.io/instance=tempo'
```

### Issue: OTel Collector Can't Connect to Tempo

**Symptom**:
- OTel Collector logs: `connection error: desc = "transport: Error while dialing: dial tcp...connect: connection refused"`
- OTel Collector logs: `rpc error: code = Unavailable`

**Root Cause**: Incorrect endpoint format for gRPC exporter.

**Solution**:
```bash
# WRONG (with http:// prefix):
exporters:
  otlp_grpc/tempo:
    endpoint: "http://tempo-distributor.catalystlab-shared.svc.cluster.local:4317"

# CORRECT (gRPC endpoints don't use http://):
exporters:
  otlp_grpc/tempo:
    endpoint: "tempo-distributor.catalystlab-shared.svc.cluster.local:4317"
```

Update `otel-collector-tempo.yaml`, apply it, and restart OTel Collector:
```bash
scp otel-collector-tempo.yaml root@<CLUSTER_IP>:/tmp/
ssh root@<CLUSTER_IP> 'kubectl apply -f /tmp/otel-collector-tempo.yaml'
ssh root@<CLUSTER_IP> 'kubectl delete pod -n catalystlab-shared -l app=otel-collector'
```

### Issue: "DoBatch: InstancesCount <= 0" Error

**Symptom**:
- Tempo distributor logs: `pusher failed to consume trace data" err="DoBatch: InstancesCount <= 0"`
- Traces not being ingested

**Root Cause**: Replication factor configuration missing for single-replica deployment.

**Solution**:
Edit `tempo-minimal-values.yaml` and add replication factor:
```yaml
distributor:
  config:
    ring:
      replication_factor: 1

ingester:
  config:
    replication_factor: 1
```

Then upgrade:
```bash
scp tempo-minimal-values.yaml root@<CLUSTER_IP>:/tmp/
ssh root@<CLUSTER_IP> 'helm upgrade tempo grafana/tempo-distributed -n catalystlab-shared -f /tmp/tempo-minimal-values.yaml'
```

### Issue: Node Pod Capacity Exceeded

**Symptom**:
```
0/4 nodes are available: 1 Too many pods, 3 node(s) had untolerated taint
```

**Root Cause**: Worker node at maximum pod capacity (typically 110 pods).

**Solution**:
Scale down non-essential Tempo components for lab environment:
```bash
# These can be scaled to 0 for minimal deployment
ssh root@<CLUSTER_IP> 'kubectl scale deployment tempo-gateway tempo-querier tempo-query-frontend tempo-compactor -n catalystlab-shared --replicas=0'

# Only keep essential components:
# - tempo-distributor (receives traces)
# - tempo-ingester (writes traces)
```

For production, either:
1. Increase node pod capacity (kubelet `--max-pods` flag)
2. Add more worker nodes
3. Deploy Tempo to dedicated namespace/nodepool

### Issue: Pods Pending/Not Scheduling

**Symptom**:
```
NAME                          READY   STATUS    RESTARTS   AGE
tempo-ingester-0              0/2     Pending   0          5m
```

**Causes**:
1. Node capacity exhausted
2. PVC provisioning failed
3. Resource requests too high

**Solutions**:
```bash
# Check node capacity
ssh root@<CLUSTER_IP> 'kubectl describe nodes | grep -A5 "Allocated resources"'

# Check PVC status
ssh root@<CLUSTER_IP> 'kubectl get pvc -n catalystlab-shared | grep tempo'

# Reduce resource requests in tempo-minimal-values.yaml
# Then upgrade
```

### Issue: No Traces in Tempo

**Symptom**: OTel Collector running, but no traces in Tempo.

**Debug steps**:
```bash
# 1. Check OTel Collector exporter
ssh root@<CLUSTER_IP> 'kubectl logs -n catalystlab-shared deployment/otel-collector | grep tempo'

# 2. Check Tempo distributor is receiving spans
ssh root@<CLUSTER_IP> 'kubectl logs -n catalystlab-shared deployment/tempo-distributor | grep "spans received"'

# 3. Verify service resolution
ssh root@<CLUSTER_IP> 'kubectl exec -n catalystlab-shared deployment/otel-collector -- nslookup tempo-distributor.catalystlab-shared.svc.cluster.local'

# 4. Test direct connection
ssh root@<CLUSTER_IP> 'kubectl run test --rm -it --image=alpine -- nc -zv tempo-distributor.catalystlab-shared.svc.cluster.local 4317'
```

### Issue: Kiali Can't Query Tempo

**Symptom**: Kiali shows "Tracing unavailable" or traces don't load.

**Debug steps**:
```bash
# 1. Verify Kiali config
ssh root@<CLUSTER_IP> 'kubectl get cm kiali -n istio-system -o yaml | grep -A10 "tracing:"'

# 2. Test query frontend from Kiali pod
ssh root@<CLUSTER_IP> 'kubectl exec -n istio-system deployment/kiali -- curl -I http://tempo-query-frontend.catalystlab-shared.svc.cluster.local:3200'

# 3. Check Kiali logs
ssh root@<CLUSTER_IP> 'kubectl logs -n istio-system deployment/kiali | grep -i tempo'
```

### Issue: High Memory Usage

**Symptom**: Ingester pods using too much memory.

**Solutions**:
```bash
# 1. Reduce ingester flush interval (flush more frequently)
# Edit tempo-minimal-values.yaml:
ingester:
  config:
    max_block_duration: 2m  # Default: 5m

# 2. Increase memory limits
ingester:
  resources:
    limits:
      memory: 2Gi  # Increase from 1Gi

# 3. Scale horizontally (more ingesters)
ssh root@<CLUSTER_IP> 'kubectl scale statefulset tempo-ingester -n catalystlab-shared --replicas=2'
```

### Issue: Slow Queries

**Causes**:
1. Too many blocks to scan
2. Large trace spans
3. Insufficient querier replicas

**Solutions**:
```bash
# 1. Enable query caching (query frontend)
# Already enabled in tempo-minimal-values.yaml

# 2. Increase querier replicas
ssh root@<CLUSTER_IP> 'kubectl scale deployment tempo-querier -n catalystlab-shared --replicas=3'

# 3. Reduce retention (fewer blocks to scan)
# Edit tempo-minimal-values.yaml compactor.config.compaction.block_retention

# 4. Use more specific trace queries
# Instead of: service=llamastack
# Use: service=llamastack AND span.duration > 1s
```

## Upgrading

### Helm Upgrade

```bash
# 1. Update Helm repo
ssh root@<CLUSTER_IP> 'helm repo update grafana'

# 2. Check new version
ssh root@<CLUSTER_IP> 'helm search repo grafana/tempo-distributed --versions | head'

# 3. Upgrade (preserves data)
ssh root@<CLUSTER_IP> 'helm upgrade tempo grafana/tempo-distributed \
  -n catalystlab-shared \
  -f /tmp/tempo-minimal-values.yaml'

# 4. Monitor rollout
ssh root@<CLUSTER_IP> 'kubectl rollout status deployment/tempo-distributor -n catalystlab-shared'
```

### Migration to Object Storage (Production)

**Current**: Local filesystem (lab only)
**Production**: S3/GCS/Azure Blob

**Migration steps**:

1. **Create S3 bucket** (or GCS/Azure equivalent)

2. **Update values**:
```yaml
storage:
  trace:
    backend: s3
    s3:
      bucket: tempo-traces
      endpoint: s3.amazonaws.com
      access_key: ${S3_ACCESS_KEY}
      secret_key: ${S3_SECRET_KEY}
```

3. **Create secret**:
```bash
ssh root@<CLUSTER_IP> 'kubectl create secret generic tempo-s3-credentials \
  -n catalystlab-shared \
  --from-literal=access_key=AKIA... \
  --from-literal=secret_key=...'
```

4. **Upgrade Helm release**:
```bash
ssh root@<CLUSTER_IP> 'helm upgrade tempo grafana/tempo-distributed \
  -n catalystlab-shared \
  -f /tmp/tempo-production-values.yaml'
```

## Uninstallation

⚠️ **WARNING**: This will delete all stored traces.

```bash
# 1. Remove Helm release
ssh root@<CLUSTER_IP> 'helm uninstall tempo -n catalystlab-shared'

# 2. Delete PVCs (optional - keeps data if reinstalling)
ssh root@<CLUSTER_IP> 'kubectl delete pvc -n catalystlab-shared -l app.kubernetes.io/instance=tempo'

# 3. Remove ingress
ssh root@<CLUSTER_IP> 'kubectl delete ingress tempo -n catalystlab-shared'

# 4. Revert OTel Collector to MLflow-only
# Apply original otel-collector.yaml (before Tempo migration)

# 5. Revert Kiali config (if needed)
# Restore from backup: /tmp/kiali-config-backup.yaml
```

## Migration from Jaeger

**Completed**: March 12, 2026

**What changed**:
1. ✅ Tempo deployed with distributed architecture
2. ✅ OTel Collector exporter changed from `otlp_grpc/jaeger` to `otlp_grpc/tempo`
3. ✅ Kiali tracing provider changed from `jaeger` to `tempo`
4. ✅ Jaeger deployment, services, and ingress removed
5. ✅ MLflow continues to receive traces (no change)

**Migration commands used**:
```bash
# Deploy Tempo
helm install tempo grafana/tempo-distributed -n catalystlab-shared -f tempo-minimal-values.yaml

# Update OTel Collector
kubectl apply -f otel-collector-tempo.yaml

# Update Kiali
kubectl patch configmap kiali -n istio-system --patch-file kiali-tempo-patch.yaml
kubectl rollout restart deployment kiali -n istio-system

# Remove Jaeger
kubectl delete deployment jaeger -n catalystlab-shared
kubectl delete service jaeger-collector jaeger-query -n catalystlab-shared
kubectl delete ingress jaeger -n catalystlab-shared
```

## Performance Tuning

### Lab Environment (Current)

**Configuration**: `tempo-minimal-values.yaml`

- **Ingester**: 100m CPU, 256Mi RAM
- **Distributor**: 100m CPU, 128Mi RAM
- **Querier**: 50m CPU, 128Mi RAM
- **Compactor**: 50m CPU, 128Mi RAM
- **Replicas**: 1 each
- **Storage**: Local PVCs (10Gi ingester, 5Gi compactor)

**Suitable for**: <1000 traces/min, <10 concurrent queries

### Production Environment

**Recommended configuration**:

```yaml
distributor:
  replicas: 3
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2
      memory: 2Gi

ingester:
  replicas: 3
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 2
      memory: 4Gi

querier:
  replicas: 3
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2
      memory: 2Gi

storage:
  trace:
    backend: s3
    s3:
      bucket: tempo-production-traces
```

**Suitable for**: >10,000 traces/min, >100 concurrent queries

## Security Considerations

⚠️ **Current deployment**: Lab environment - NO authentication or encryption

**Production requirements**:

1. **TLS/HTTPS**:
```yaml
gateway:
  tls:
    enabled: true
    cert_file: /etc/tempo/tls/cert.pem
    key_file: /etc/tempo/tls/key.pem
```

2. **Authentication**:
   - Use OAuth2 proxy for UI access
   - Implement RBAC for Kubernetes API access
   - Use IAM roles for S3/GCS access (no hardcoded credentials)

3. **Network Policies**:
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: tempo-network-policy
  namespace: catalystlab-shared
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/instance: tempo
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: otel-collector
    ports:
    - port: 4317
```

4. **Multi-tenancy**:
```yaml
multitenancyEnabled: true
# Requires tenant ID in trace headers
```

## Current Deployment

**Active Configuration**: `tempo-single-node-ha.yaml` (deployed March 23, 2026)

**Reason**: Single-worker cluster requires special HA configuration to prevent ring failures. Standard configuration (`tempo-minimal-values.yaml`) with 1 replica + replication_factor 1 caused "too many unhealthy instances in the ring" errors during pod restarts.

**Key Settings**:
- Ingester replicas: 2, replication_factor: 2
- Distributor replicas: 2, replication_factor: 2
- Storage: MinIO S3 (tempo-traces bucket)
- Anti-affinity: disabled (allows multiple pods per node)
- Memcached: disabled

**Stability**: Ring redundancy ensures queries succeed during pod restarts. Trade-off: Multiple replicas on same node reduces node-level HA.

## Deployment Status

Use these commands to verify your deployment:

```bash
# Check all Tempo resources
ssh root@<CLUSTER_IP> 'kubectl get pods,svc,pvc,ingress -n catalystlab-shared -l app.kubernetes.io/instance=tempo'

# Expected resources (minimal lab deployment):
# Pods:
#   - tempo-distributor-xxx (1/1 Running) - trace ingestion
#   - tempo-ingester-0 (1/1 Running) - trace storage
#
# Services:
#   - tempo-distributor (ClusterIP, ports 4317,4318,3200,9095,55680)
#   - tempo-distributor-discovery (ClusterIP None)
#   - tempo-ingester (ClusterIP, ports 3200,9095)
#   - tempo-ingester-discovery (ClusterIP None)
#   - tempo-gossip-ring (ClusterIP None, port 7946)
#   - tempo-query-frontend (ClusterIP, ports 3200,9095)
#   - tempo-querier, tempo-compactor, tempo-gateway (ClusterIP)
#
# PVCs:
#   - storage-tempo-ingester-0 (Bound, 10Gi)
#
# Ingress:
#   - tempo (hosts: tempo.<CLUSTER_IP>.nip.io)
```

### Access Information

- **Tempo Query Frontend (internal):** `http://tempo-query-frontend.catalystlab-shared.svc.cluster.local:3200`
- **Tempo UI (external via Grafana):** `http://tempo.<CLUSTER_IP>.nip.io`
- **Tempo Distributor (internal):** `tempo-distributor.catalystlab-shared.svc.cluster.local:4317` (gRPC)
- **MLflow UI:** `http://mlflow.<CLUSTER_IP>.nip.io` (continues to work independently)
- **Kiali UI:** `http://kiali.<CLUSTER_IP>.nip.io` (for service mesh visualization)

### Minimal Lab Configuration Summary

**Running Components** (essential only):
- Distributor: Receives traces from OTel Collector
- Ingester: Writes traces to storage

**Scaled to 0** (non-essential for lab):
- Query Frontend: Can be scaled up when needed for queries
- Querier: Can be scaled up when needed for queries
- Compactor: Can be scaled up periodically for maintenance
- Gateway: Not needed when accessing components directly

**Important Notes**:
- Replication factor set to 1 (single replica)
- Istio sidecars explicitly disabled
- Local filesystem storage (suitable for lab only)
- No authentication or TLS (lab use only)

## References

- **Grafana Tempo Documentation**: https://grafana.com/docs/tempo/latest/
- **Helm Chart**: https://github.com/grafana/helm-charts/tree/main/charts/tempo-distributed
- **TraceQL Query Language**: https://grafana.com/docs/tempo/latest/traceql/
- **OpenTelemetry Integration**: https://grafana.com/docs/tempo/latest/configuration/
- **Kiali Tempo Integration**: https://kiali.io/docs/configuration/

## Support

**Cluster**: <CLUSTER_IP> (SSH access: `ssh root@<CLUSTER_IP>`)
**Namespace**: catalystlab-shared
**Helm Release**: tempo
**Chart Version**: 1.61.3 (Tempo v2.9.0)
**Deployment Date**: March 12, 2026
**Deployed By**: Claude Code + User collaboration
