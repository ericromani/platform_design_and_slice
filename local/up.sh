#!/usr/bin/env bash
# Brings up the local "cloud": kind cluster (EKS stand-in), LocalStack (AWS stand-in) and
# an OCI registry (ECR stand-in), all on the same container network so pods can reach
# http://localstack:4566 and the node can pull from kind-registry:5000.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=local/env.sh
source "$ROOT/local/env.sh"

CLUSTER=platform
NET=kind
REG=kind-registry
LOCALSTACK_IMAGE="docker.io/localstack/localstack:4.14.0"

if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  echo "==> creating kind cluster '$CLUSTER'"
  kind create cluster --config "$ROOT/local/kind-config.yaml" --kubeconfig "$KUBECONFIG" --wait 120s
else
  echo "==> kind cluster '$CLUSTER' exists"
  kind export kubeconfig --name "$CLUSTER" --kubeconfig "$KUBECONFIG"
fi

if ! podman container exists "$REG"; then
  echo "==> starting registry ($REG, host port 5001)"
  podman run -d --restart=always --name "$REG" --network "$NET" -p 127.0.0.1:5001:5000 docker.io/library/registry:2
fi

# Map localhost:5001 (what the host pushes to) to the registry container on the node.
NODE="${CLUSTER}-control-plane"
podman exec "$NODE" mkdir -p /etc/containerd/certs.d/localhost:5001
podman exec -i "$NODE" sh -c 'cat > /etc/containerd/certs.d/localhost:5001/hosts.toml' <<TOML
[host."http://${REG}:5000"]
TOML

if ! podman container exists localstack; then
  echo "==> starting LocalStack ($LOCALSTACK_IMAGE, host port 4566)"
  podman run -d --restart=always --name localstack --network "$NET" \
    -p 127.0.0.1:4566:4566 \
    -e SERVICES=iam,sts,sqs,dynamodb,sns,s3,ssm,ec2 \
    -e LOCALSTACK_HOST=localstack:4566 \
    "$LOCALSTACK_IMAGE"
fi

echo "==> waiting for LocalStack"
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:4566/_localstack/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS http://localhost:4566/_localstack/health | python3 -c 'import json,sys; d=json.load(sys.stdin)["services"]; print("   localstack:", ", ".join(f"{k}={v}" for k,v in sorted(d.items()) if v!="disabled"))'

# S3 SDKs (and the ACK S3 controller) use virtual-hosted-style URLs:
# http://<bucket>.localstack:4566. Rewrite any *.localstack name to the LocalStack
# container so bucket hostnames resolve inside the cluster.
if ! kubectl -n kube-system get configmap coredns -o jsonpath='{.data.Corefile}' | grep -q 'localstack'; then
  echo "==> CoreDNS: resolve *.localstack to LocalStack"
  kubectl -n kube-system get configmap coredns -o jsonpath='{.data.Corefile}' \
    | python3 -c 'import re,sys; print(re.sub(r"^(\s*)ready$", r"\1ready\n\1rewrite name regex (.+)\\.localstack\\.$ localstack. answer auto", sys.stdin.read(), count=1, flags=re.M))' \
    > "$ROOT/.tools/Corefile"
  kubectl -n kube-system create configmap coredns --from-file=Corefile="$ROOT/.tools/Corefile" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl -n kube-system rollout restart deploy/coredns >/dev/null
  kubectl -n kube-system rollout status deploy/coredns --timeout=120s >/dev/null
fi

echo "==> verifying pod -> LocalStack reachability"
kubectl run netcheck --rm -i --restart=Never --image=docker.io/curlimages/curl:8.17.0 -- \
  curl -fsS -o /dev/null -w "   pod reached localstack: HTTP %{http_code}\n" http://localstack:4566/_localstack/health
echo "local cloud is up (kubeconfig: $KUBECONFIG)"
