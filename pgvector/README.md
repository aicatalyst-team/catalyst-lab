# PostgreSQL + pgvector on Kubernetes

Deploy PostgreSQL 17 with the [pgvector](https://github.com/pgvector/pgvector) extension on Kubernetes using the [CloudNativePG](https://cloudnative-pg.io/) operator.

**Namespace:** `catalystlab-shared`

## Prerequisites

- `kubectl` configured with cluster access
- `helm` v3+ installed
- A node with sufficient resources for PostgreSQL

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

### 2. Create the shared namespace (if it doesn't exist)

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

## ANN Index Dimension Limit

pgvector 0.8.1 enforces maximum dimension limits on ANN indexes (HNSW and IVFFlat):

| Vector Type | Max Index Dims | Storage per Dim |
|-------------|:--------------:|:---------------:|
| `vector` (float32) | 2,000 | 4 bytes |
| `halfvec` (float16) | 4,000 | 2 bytes |
| `bit` (binary) | 64,000 | 1/8 byte |

### Current State

The lab uses **Qwen3-Embedding-8B** which outputs **4096-dimension** embeddings as `vector(4096)`. Since 4096 exceeds the 2,000-dimension ANN index limit for the `vector` type, similarity searches use **sequential scan** (no ANN index). With demo-scale data (1 row, 152 KB), this has no measurable performance impact.

### Workaround Options

Listed in order of practicality for this lab:

1. **Accept sequential scan (current)** -- For demo-scale data (<10K vectors), sequential scan performs comparably to indexed search. No changes needed.

2. **Matryoshka dimension reduction** -- Qwen3-Embedding-8B supports [MRL (Matryoshka Representation Learning)](https://github.com/QwenLM/Qwen3-Embedding). It can output truncated embeddings (e.g., 512, 1024, 2048 dims) with graceful quality degradation. However, vLLM currently rejects the `dimensions` parameter for this model, treating it as non-matryoshka. The LLaMA Stack Containerfile patches around this by removing `dimensions` entirely. Fixing this upstream (in vLLM or LLaMA Stack) would allow requesting ≤2000-dim embeddings and creating HNSW indexes.

3. **halfvec with truncation** -- The `halfvec` type supports up to 4,000 dimensions. Truncating from 4096 to 4000 dims (dropping 96 trailing dimensions) loses minimal information. This requires: changing the column type to `halfvec(4000)`, truncating vectors on insert, and creating an HNSW index with `halfvec_l2_ops`. Example:
   ```sql
   ALTER TABLE vectors ALTER COLUMN embedding TYPE halfvec(4000)
     USING embedding::vector(4000)::halfvec(4000);
   CREATE INDEX ON vectors USING hnsw (embedding halfvec_l2_ops);
   ```

4. **Switch embedding model** -- Use a model with ≤2000 native dimensions (e.g., many models output 768 or 1536 dims). Requires re-embedding all existing vectors.

### Decision

Sequential scan is acceptable for the lab's demo-scale data. For production workloads (>10K vectors), the recommended path is Matryoshka dimension reduction to ≤2000 dims once the vLLM `dimensions` parameter is supported for this model.

### HNSW Tuning Reference

If an HNSW index is created in the future, these parameters control the quality/performance tradeoff:

| Parameter | Default | Range | Effect |
|-----------|:-------:|:-----:|--------|
| `m` | 16 | 2-100 | Connections per layer. Higher = better recall, larger index. |
| `ef_construction` | 64 | 4-1000 | Build-time candidate list. Higher = better index quality, slower build. Must be ≥ 2*m. |
| `ef_search` | 40 | 1-1000 | Query-time candidate list. Higher = better recall, slower search. Set per-query via `SET LOCAL hnsw.ef_search = N`. |

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
| Node | (set via nodeSelector) | Pinned to target node |

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
