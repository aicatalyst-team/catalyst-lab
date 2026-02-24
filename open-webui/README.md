# Open WebUI

Chat interface deployed by Eitan for team use. Provides a browser-based UI for interacting with LLM endpoints.

## Live State (discovered 2026-02-23)

| Property | Value |
|----------|-------|
| Namespace | `open-webui` |
| Image | `ghcr.io/open-webui/open-webui:0.7.2` |
| Helm chart | `open-webui-10.2.1` |
| External URL | `https://open-webui.<INGRESS_IP>.nip.io` (TLS) |
| Deployed | 2026-01-15 (Helm), ingress added 2026-01-16 |
| Owner | Eitan |

## Architecture

```
Browser ──HTTPS──► nginx ingress (TLS termination)
                        │
                        ▼
              open-webui pod :8080
                        │
              ┌─────────┴──────────┐
              ▼                    ▼
        Redis :6379          PVC /app/backend/data (2Gi)
        (websocket state)    (SQLite DB, user config,
                              model connections)
```

Model connections are configured through the Open WebUI settings UI and persisted in the SQLite database on the PVC — not in environment variables. The `OPENAI_API_BASE_URL` env var sets only the default; actual model endpoints are added per-user or per-admin in the UI.

## Deployment Details

- **Deployed via Helm** — chart `open-webui-10.2.1`, managed in namespace `open-webui`
- **TLS** — nginx ingress with `ssl-redirect: true`, cert in secret `open-webui-tls`
- **WebSocket** — enabled, backed by Redis for multi-pod scalability
- **Ollama** — disabled (`ENABLE_OLLAMA_API: False`)
- **Storage** — 2Gi PVC (`local-path`) for user data, chat history, model config

## Connecting to LLaMA Stack

Open WebUI can be pointed at LLaMA Stack via the admin settings UI:

1. Navigate to **Admin Panel → Settings → Connections**
2. Add an OpenAI-compatible connection:
   - **URL**: `http://llamastack.catalystlab-shared.svc.cluster.local:8321`
   - **API Key**: any non-empty string (LLaMA Stack doesn't validate it)
3. The model `vllm/RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8` will appear in the model selector

Alternatively, point directly at the KServe workload service for lower latency (bypasses LLaMA Stack tracing).

## Helm Install Reference

The deployment was created with:

```bash
helm repo add open-webui https://helm.openwebui.com/
helm upgrade --install open-webui open-webui/open-webui \
  --namespace open-webui --create-namespace \
  --set service.type=ClusterIP \
  --set ingress.enabled=true \
  --set ingress.class=nginx \
  --set ingress.host=open-webui.<INGRESS_IP>.nip.io
```

No values file is committed — the deployment is Helm-managed. To inspect current values:

```bash
helm get values open-webui -n open-webui
```

## Notes

- Model endpoint configuration is stored in the SQLite PVC, not in the Helm values or K8s manifests — changes survive pod restarts but are not version-controlled
- The `OPENAI_API_KEY` env var in the deployment is a dummy placeholder (`0p3n-w3bu!`) — Open WebUI accepts any non-empty string for OpenAI-compatible endpoints that don't enforce authentication
- WebSocket timeout is extended to 3600s on the nginx ingress to support long-running chat sessions
- No manifests are committed here — Open WebUI is managed solely via Helm; consult Eitan for configuration changes
