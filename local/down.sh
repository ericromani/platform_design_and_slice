#!/usr/bin/env bash
# Tears down the local cloud: kind cluster, LocalStack and the registry. Terraform state
# for envs/local is removed too, since it described LocalStack resources that no longer exist.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=local/env.sh
source "$ROOT/local/env.sh"
kind delete cluster --name platform 2>/dev/null || true
for c in localstack kind-registry; do podman rm -f "$c" >/dev/null 2>&1 || true; done
rm -f "$ROOT"/infra/terraform/envs/local/terraform.tfstate* "$ROOT"/local/generated/*.yaml
echo "local cloud removed"
