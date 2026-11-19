#!/usr/bin/env bash
# Package the microservice chart and push it to the platform OCI registry.
#   publish_chart.sh <oci-registry-url> [--plain-http]
#   e.g. publish_chart.sh oci://localhost:5001/charts --plain-http      (local)
#        publish_chart.sh oci://123456789012.dkr.ecr.us-east-1.amazonaws.com/charts (CI)
# Refuses to overwrite a published version: bump Chart.yaml instead (charts are immutable).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
CHART="$ROOT/platform/charts/microservice"
REGISTRY="${1:?registry url, e.g. oci://localhost:5001/charts}"
shift
VERSION="$(awk '/^version:/ {print $2}' "$CHART/Chart.yaml")"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

if helm show chart "$REGISTRY/microservice" --version "$VERSION" "$@" >/dev/null 2>&1; then
  if [[ "${ALLOW_REPUBLISH:-}" == "1" ]]; then
    echo "microservice $VERSION already published; ALLOW_REPUBLISH=1 (local only) so pushing again"
  else
    echo "microservice $VERSION is already published to $REGISTRY; bump version in Chart.yaml" >&2
    exit 1
  fi
fi
helm lint "$CHART" -f "$CHART/ci/full-values.yaml" >/dev/null
helm package "$CHART" -d "$OUT" >/dev/null
helm push "$OUT/microservice-$VERSION.tgz" "$REGISTRY" "$@"
