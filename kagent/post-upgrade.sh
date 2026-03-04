#!/usr/bin/env bash
# post-upgrade.sh -- Run after every `helm upgrade kagent` to restore scoped RBAC
#
# The Helm chart recreates kagent-tools-cluster-admin-rolebinding on every upgrade.
# This script removes the over-permissive binding and applies our scoped RBAC.
#
# Usage:
#   helm upgrade kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
#     --namespace kagent --version 0.7.18 -f kagent/values.yaml
#   ./kagent/post-upgrade.sh
#
#   # Don't forget to re-patch the ModelConfig baseUrl:
#   kubectl patch modelconfig default-model-config -n kagent --type merge \
#     -p "$(cat kagent/modelconfig-patch.yaml)"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Removing Helm-managed cluster-admin binding..."
kubectl delete clusterrolebinding kagent-tools-cluster-admin-rolebinding --ignore-not-found

echo "==> Applying scoped RBAC..."
kubectl apply -f "${SCRIPT_DIR}/rbac-scoped.yaml"

echo "==> Verifying..."
echo "ClusterRoleBindings for kagent-tools:"
kubectl get clusterrolebinding -o custom-columns='NAME:.metadata.name,ROLE:.roleRef.name' \
  | grep kagent-tools || true

echo ""
echo "RoleBindings in catalystlab-shared:"
kubectl get rolebinding -n catalystlab-shared -o custom-columns='NAME:.metadata.name,ROLE:.roleRef.name' \
  | grep kagent-tools || true

echo ""
echo "Done. kagent-tools now has:"
echo "  - Cluster-wide read (get/list/watch)"
echo "  - Write access in catalystlab-shared only"
