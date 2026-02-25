# Contributing to catalyst-lab

## Setup

1. Clone the repo and install pre-commit hooks:

   ```bash
   uv tool install pre-commit
   pre-commit install
   ```

2. Generate the detect-secrets baseline (first time only):

   ```bash
   uv tool run detect-secrets scan --exclude-files '\.secrets\.baseline' > .secrets.baseline
   ```

   `.secrets.baseline` is gitignored and stays local.

## Sensitive Data Policy

**Never commit:**

| Type | Example |
|------|---------|
| IPv4 addresses | cluster IPs, node IPs, service CIDRs |
| Email / usernames | personal or service accounts |
| Passwords / API keys | any literal credential value |
| Internal hostnames | node FQDNs, cluster-internal DNS names |
| Kubeconfig fragments | bearer tokens, client certificates |

**Always use:**

- `<PLACEHOLDER>` in documentation and example manifests
- `secretKeyRef` / `configMapKeyRef` in Kubernetes manifests
- `$(VAR_NAME)` for env var references within manifests

The pre-commit hooks will block commits that violate these rules.

## Pre-commit Hook Details

Three layers of protection run on every commit:

1. **`pre-commit-hooks`** — standard hygiene: private key detection, YAML validity, merge conflict markers, trailing whitespace.
2. **`detect-secrets`** — high-entropy string detection, generic password patterns, base64-encoded secrets.
3. **`check-sensitive-data`** (local, `scripts/check-sensitive-data.py`) — catches IPv4 addresses, email addresses, and hardcoded `password:`/`api_key:`/`secret:`/`token:` YAML keys.

### False Positives

If a file legitimately contains a pattern that triggers a false positive:

- For `detect-secrets`: update the baseline with `detect-secrets scan --update .secrets.baseline <file>`
- For `check-sensitive-data`: the hook allows `<PLACEHOLDER>`, `secretKeyRef`, `configMapKeyRef`, `valueFrom`, and `${...}` references — rewrite the offending line to use one of these forms.

## Directory Structure

```
<component>/
├── README.md         # deployment reference, caveats, verification steps
├── *.yaml            # Kubernetes manifests
└── ...
```

Each component lives in its own directory. Add a `README.md` documenting:

- How to apply the manifests
- Environment-specific values that need substituting
- Known caveats and gotchas

## Manifests Style

- Explicit `namespace:` on every resource
- No literal credential values — use `secretKeyRef` or `configMapKeyRef`
- `<PLACEHOLDER>` for values filled in at apply time
- Comments on non-obvious configuration choices

## PR Guidelines

- One logical change per PR
- Reference the component in the PR title (e.g. `llamastack: update config`)
- Do not include `CLUSTER.md`, `PLAN.md`, or `journal/` files
- Ensure `pre-commit run --all-files` passes before opening a PR
