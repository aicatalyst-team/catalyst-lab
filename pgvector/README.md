# PostgreSQL + pgvector on Kubernetes

Deploy PostgreSQL 17 with the [pgvector](https://github.com/pgvector/pgvector) extension on Kubernetes using the [CloudNativePG](https://cloudnative-pg.io/) operator.

**Target node:** `worker-gpu2`
**Namespace:** `catalystlab-shared`

## Prerequisites

- `kubectl` configured with cluster access
- `helm` v3+ installed
- Access to the `worker-gpu2` node

## Installation

### 1. Install the CloudNativePG operator

Add the Helm repo and install the operator:

```bash
helm repo add cnpg https://cloudnative-pg.github.io/charts
helm repo update
```

```bash
helm install cnpg cnpg/cloudnative-pg \
  --namespace cnpg-system \
  --create-namespace
```

Verify the operator is running:

```bash
kubectl get pods -n cnpg-system
```

Expected output:

```
NAME                    READY   STATUS    RESTARTS   AGE
cnpg-cloudnative-pg-*   1/1     Running   0          ...
```

### 2. Create the namespace

```bash
kubectl create namespace catalystlab-shared
```

### 3. Deploy the PostgreSQL cluster

```bash
kubectl apply -f cluster.yaml
```

### 4. Verify the deployment

Check cluster status:

```bash
kubectl get cluster -n catalystlab-shared
```

Expected output shows `Cluster in healthy state`:

```
NAME               AGE   INSTANCES   READY   STATUS                     PRIMARY
pgvector-cluster   ..s   1           1       Cluster in healthy state   pgvector-cluster-1
```

Check the pod is running on `worker-gpu2`:

```bash
kubectl get pods -n catalystlab-shared -o wide
```

Verify pgvector extension is loaded:

```bash
kubectl exec -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U vectordb -d vectordb \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

Expected output:

```
 extname | extversion
---------+------------
 vector  | 0.8.0
```

## Connecting to the database

### Get credentials

The operator auto-generates credentials and stores them in a Kubernetes Secret:

```bash
# Get the password
kubectl get secret pgvector-cluster-app -n catalystlab-shared \
  -o jsonpath='{.data.password}' | base64 -d && echo

# Get the full connection URI
kubectl get secret pgvector-cluster-app -n catalystlab-shared \
  -o jsonpath='{.data.uri}' | base64 -d && echo
```

### Connection details (from within the cluster)

| Parameter | Value |
|-----------|-------|
| Host      | `pgvector-cluster-rw.catalystlab-shared.svc` |
| Port      | `5432` |
| Database  | `vectordb` |
| User      | `vectordb` |

### Interactive psql session

```bash
kubectl exec -it -n catalystlab-shared pgvector-cluster-1 -- \
  psql -U vectordb -d vectordb
```

### Port-forward for local access

```bash
kubectl port-forward -n catalystlab-shared svc/pgvector-cluster-rw 5432:5432
```

Then connect locally:

```bash
psql -h localhost -U vectordb -d vectordb
```

## Quick start: using pgvector

Once connected, you can create a table with vector columns:

```sql
-- Create a table with a 3-dimensional vector column
CREATE TABLE items (
  id BIGSERIAL PRIMARY KEY,
  content TEXT,
  embedding VECTOR(3)
);

-- Insert sample data
INSERT INTO items (content, embedding) VALUES
  ('hello world', '[1, 2, 3]'),
  ('goodbye world', '[4, 5, 6]');

-- Find nearest neighbors using L2 distance
SELECT content, embedding
FROM items
ORDER BY embedding <-> '[1, 2, 3]'
LIMIT 5;

-- Create an index for faster queries (recommended for large datasets)
CREATE INDEX ON items USING hnsw (embedding vector_l2_ops);
```

## Configuration

The cluster is configured in `cluster.yaml` with the following settings:

| Setting | Value | Description |
|---------|-------|-------------|
| PostgreSQL version | 17 | Latest stable release |
| Instances | 1 | Single instance (no HA) |
| Storage | 20Gi | `local-path` storage class |
| CPU requests/limits | 1 / 4 | CPU allocation |
| Memory requests/limits | 2Gi / 4Gi | Memory allocation |
| shared_buffers | 512MB | PostgreSQL shared memory |
| max_connections | 200 | Maximum concurrent connections |
| Node | worker-gpu2 | Pinned via nodeSelector |

## Uninstall

Remove the PostgreSQL cluster:

```bash
kubectl delete cluster pgvector-cluster -n catalystlab-shared
kubectl delete namespace catalystlab-shared
```

Remove the CloudNativePG operator:

```bash
helm uninstall cnpg -n cnpg-system
kubectl delete namespace cnpg-system
```

Remove the CRDs (optional):

```bash
kubectl get crds | grep cnpg | awk '{print $1}' | xargs kubectl delete crd
```
