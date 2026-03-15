# MCPMark Benchmark

Runs [MCPMark](https://github.com/eval-sys/mcpmark) benchmark tasks as Kubernetes Jobs against the lab stack.

MCPMark evaluates LLM agent capabilities on real MCP tool-use tasks (file operations, database queries).

## How It Works

```
MCPMark Job Pod
  |
  |-- LLM calls --> LLaMA Stack --> vLLM (traced via OTel)
  |
  |-- MCP tool calls --> internal stdio subprocess (NOT through ToolHive)
       |-- filesystem: npx @modelcontextprotocol/server-filesystem
       |-- postgres: pipx run postgres-mcp --> CNPG (pre-populated sample DBs)
```

- LLM inference traces appear in Jaeger and MLflow via the OTel pipeline
- MCP tool calls are local to the container (see "Architectural Gap" section below)

## Running Benchmarks

```bash
# Create the API key secret (LiteLLM requires one even for local backends)
kubectl create secret generic mcpmark-api-key -n catalystlab-shared \
  --from-literal=OPENAI_API_KEY=dummy

# Run filesystem benchmark (file_property category)
kubectl apply -f mcpmark/benchmark-job.yaml

# Watch progress
kubectl logs -n catalystlab-shared job/mcpmark-filesystem -f

# Check results
kubectl logs -n catalystlab-shared job/mcpmark-filesystem | grep -E "Tasks passed|Total time"
```

## Task Categories

### Filesystem

| Category | Tasks | Description |
|----------|-------|-------------|
| file_property | 2+ | File metadata analysis, size classification |
| file_context | 2+ | Content extraction and understanding |
| folder_structure | 2+ | Directory organization tasks |
| papers | 2+ | Academic paper file operations |
| student_database | 2+ | CSV/file-based data management |
| legal_document | 2+ | Document structure analysis |

### PostgreSQL

| Category | Tasks | Description |
|----------|-------|-------------|
| security | 2+ | SQL injection prevention, access control |
| chinook | 2+ | Music database queries (requires download) |
| dvdrental | 2+ | Rental database queries (requires download) |
| employees | 2+ | Employee database queries (requires download) |

**Sample Data**: The 5 PostgreSQL sample databases (chinook, dvdrental, employees, sports, lego)
are pre-populated in CNPG. MCPMark's `PostgresStateManager` detects them and creates task-specific
databases from these templates at runtime -- no external downloads needed.

## Customization

Edit the Job `command` to change what runs:

```yaml
command:
  - python3
  - -m
  - pipeline
  - --mcp=filesystem                    # or postgres
  - --models=openai/vllm/RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8
  - --tasks=file_property               # category or category/task
  - --exp-name=catalyst-lab-benchmark
  - --k=1                               # number of runs
```

The model name must include the `vllm/` provider prefix to match the LLaMA Stack model registry.
LiteLLM's `openai/` prefix tells it to use the OpenAI-compatible provider.

## Configuration

| Environment Variable | Value | Purpose |
|---------------------|-------|---------|
| `OPENAI_API_BASE` | `http://llamastack:8321/v1` | LLaMA Stack endpoint |
| `OPENAI_API_KEY` | `dummy` (via secret) | Required by LiteLLM |
| `FILESYSTEM_TEST_ROOT` | `/tmp/mcpmark-tests` | Writable sandbox |
| `POSTGRES_HOST` | CNPG service | Benchmark database |

## Architectural Gap: stdio vs ToolHive

### The Problem

MCPMark spawns its own MCP servers as **stdio subprocesses** inside the benchmark container.
It does **not** use the ToolHive-managed MCP servers or the Envoy AI Gateway MCPRoute deployed
in the lab. This means:

1. **No MCP tool call traces through ToolHive/Envoy** -- tool calls are local to the container
2. **No gateway-level observability** -- the MCPRoute traffic metrics and traces don't include
   benchmark tool calls
3. **Benchmark results don't reflect gateway overhead** -- latency measurements exclude the
   network hop through ToolHive proxy and Envoy gateway

### How MCPMark Starts MCP Servers

MCPMark's `MCPMarkAgent._create_mcp_server()` categorizes services into two groups:

| Transport | Services | How It Works |
|-----------|----------|--------------|
| **stdio** | filesystem, postgres, notion, playwright | Spawns subprocess via `npx`/`pipx`, communicates over stdin/stdout |
| **HTTP** | github | Connects to remote URL (`https://api.githubcopilot.com/mcp/`) |

For **filesystem**, it runs: `npx @modelcontextprotocol/server-filesystem <test_dir>`
For **postgres**, it runs: `pipx run postgres-mcp --access-mode=unrestricted` with `DATABASE_URI` env var

Both spawn a new process inside the MCPMark container, independent of our ToolHive servers.

### What a Fix Would Require

MCPMark already has `MCPHttpServer` support (used for GitHub). Patching it to use HTTP endpoints
for filesystem/postgres would involve:

1. **Add filesystem/postgres to HTTP_SERVICES** -- move them from the stdio list or make
   transport configurable per-service
2. **Accept a URL parameter** -- pass the ToolHive proxy URL
   (e.g., `http://mcp-filesystem-mcp-proxy.catalystlab-shared.svc:8080/mcp`) instead of
   spawning a subprocess
3. **Handle MCP session protocol** -- the `MCPHttpServer` class would need to support
   `Mcp-Session-Id` headers for streamable-http (ToolHive's transport mode)

### Effort Assessment

**Small-to-medium patch** (~100 lines). The `MCPHttpServer` class already handles HTTP
connections. The main work is:

- Making transport mode configurable via CLI flag or env var (e.g., `--mcp-transport=http`)
- Passing the remote MCP server URL as a parameter
- Adding `Mcp-Session-Id` header handling if not already present in the HTTP client

This could be submitted as an upstream PR to `eval-sys/mcpmark` or maintained as a local fork.

### Current Workaround

For now, the benchmark measures LLM reasoning + local MCP tool execution. The LLM inference
path (MCPMark -> LLaMA Stack -> vLLM) is fully traced via OTel. Only the MCP tool call leg
is untraced because it's local stdio.
