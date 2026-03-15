# ToolHive MCP Servers

MCP servers deployed via the ToolHive operator (already running in `toolhive-system`).
These servers are aggregated behind the Envoy AI Gateway MCPRoute for unified access.

## Components

| Server | Image | Transport | Tools |
|--------|-------|-----------|-------|
| filesystem-mcp | `mcp/filesystem:1.0.2` | stdio (proxied as streamable-http) | 14 file tools (read, write, search, etc.) |
| postgres-mcp | `crystaldba/postgres-mcp:0.3.0` | SSE (proxied as streamable-http) | 9 database tools (SQL, schema, health) |

Both servers have OpenTelemetry enabled, exporting to the OTel collector in `catalystlab-shared`.

## Architecture

```
Kagent Agent / MCPMark Job
        |
   MCP calls
        |
Envoy AI Gateway (MCPRoute /mcp)
    /                \
ToolHive             ToolHive
filesystem-mcp       postgres-mcp
                          |
                     CNPG PostgreSQL
                     (benchmark db)
```

## Deployment

```bash
# Create the postgres credentials secret
PG_PASS=$(kubectl get secret -n catalystlab-shared pgvector-cluster-app \
  -o jsonpath='{.data.password}' | base64 -D)
kubectl create secret generic postgres-mcp-credentials \
  -n catalystlab-shared \
  --from-literal=DATABASE_URI="postgresql://app:${PG_PASS}@pgvector-cluster-rw.catalystlab-shared.svc:5432/benchmark"

# Deploy MCP servers
kubectl apply -f toolhive/filesystem-mcp.yaml
kubectl apply -f toolhive/postgres-mcp.yaml

# Deploy the Envoy AI Gateway MCPRoute
kubectl apply -f envoy-ai-gateway/mcp-gateway.yaml
```

## Verification

```bash
# Check ToolHive MCPServer status
kubectl get mcpservers.toolhive.stacklok.dev -n catalystlab-shared

# Check pods
kubectl get pods -n catalystlab-shared | grep mcp

# Check MCPRoute
kubectl get mcproutes.aigateway.envoyproxy.io -n catalystlab-shared
```

## Notes

- The filesystem MCP server uses `/tmp` as its sandbox directory (writable in container)
- The postgres MCP server connects to a dedicated `benchmark` database on CNPG -- isolated from production databases (mlflow, llamastack, vectordb)
- ToolHive wraps stdio servers in a proxy sidecar that exposes streamable-http endpoints
- The Envoy AI Gateway MCPRoute aggregates both servers and prefixes tool names: `mcp-filesystem-mcp-proxy__read_file`, `mcp-postgres-mcp-proxy__execute_sql`, etc.
