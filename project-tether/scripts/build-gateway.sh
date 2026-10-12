#!/usr/bin/env bash
# Build the Tether Verification Gateway container image.
# Usage: ./scripts/build-gateway.sh
set -euo pipefail

IMAGE="quay.io/aicatalyst/tether-gateway:latest"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

PLATFORM="${1:-}"
PLATFORM_FLAG=""
if [ -n "$PLATFORM" ]; then
    PLATFORM_FLAG="--platform $PLATFORM"
fi

podman build \
    $PLATFORM_FLAG \
    -t "$IMAGE" \
    -f "$PROJECT_ROOT/Containerfile" \
    "$PROJECT_ROOT"

echo "Built: $IMAGE"
