# AGENTS.md — AI Agent Instructions for catalyst-lab

This file provides instructions for AI coding agents (Claude, Copilot, etc.) working in this repository.

## Repository Purpose

Kubernetes manifests and documentation for the AI Catalyst Lab shared stack. This is a **multi-tenant** lab environment — treat all resources as shared infrastructure.

## Architecture

| Component | Namespace | Notes |
|-----------|-----------|-------|
| PostgreSQL (CNPG) | `catalystlab-shared` | 3 DBs: `vectordb`, `llamastack`, `mlflow` |
| LLaMA Stack | `catalystlab-shared` | Port 8321, PostgreSQL-backed state |
| MLflow | `catalystlab-shared` | Port 5000, PVC artifact store |
| OTel Collector | `catalystlab-shared` | gRPC 4317 / HTTP 4318 |
| Open WebUI | `open-webui` | Eitan's deployment, Helm-managed |
| KServe / vLLM | `kserve-lab` | Sean's deployment — **do not modify** |
| GuideLLM | `guide-llm` | Benchmark jobs — namespace owned by team |

## Security Rules

**Never commit any of the following:**

- IPv4 addresses (cluster IPs, node IPs, service IPs)
- Email addresses or usernames
- Hardcoded credentials — passwords, API keys, tokens, secrets
- Internal hostnames or node names
- Bearer tokens or kubeconfig fragments

**Always use instead:**

- `secretKeyRef` / `configMapKeyRef` for credentials in manifests
- `<PLACEHOLDER>` format in documentation examples
- Environment variable references (`$(VAR_NAME)`) in manifests

Pre-commit hooks enforce these rules automatically. Run `pre-commit install` before your first commit.

## What NOT to Commit

| File / Path | Reason |
|-------------|--------|
| `CLUSTER.md` | Contains real cluster IPs and hostnames |
| `PLAN.md` | Contains sensitive cluster details |
| `journal/` | Work-organizing notes with real details |
| `.secrets.baseline` | Auto-generated, gitignored |

These paths are already in `.gitignore`.

## Tooling

- **Python**: use `uv run` / `uv tool` — never bare `python` or `pip`
- **Containers**: use `podman` — not `docker`
- **Registry**: `quay.io/aicatalyst` for team images,
- **Kubernetes**: `kubectl` with context pointing to the lab cluster

## File Organization

Each component gets its own directory with a `README.md`:

```
<component>/
├── README.md         # deployment reference, caveats, verification steps
├── *.yaml            # Kubernetes manifests
└── ...
```

Document discovered caveats and gotchas in the component README — this repo serves as the team's operational runbook.

## Manifests Style

- Set explicit `namespace:` on all resources
- Use `secretKeyRef` / `configMapKeyRef` — never literal credential values
- Use `<PLACEHOLDER>` for values that must be filled in before applying
- Add comments explaining non-obvious configuration choices
