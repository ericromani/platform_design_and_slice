#!/usr/bin/env bash
# Installs the platform add-ons into the current kube context. Idempotent.
#
#   install.sh [all|controllers|delivery|observability]
#
# MODE=local (default) targets kind + LocalStack: one cluster hosts both environments,
# so each environment gets its own set of ACK controllers, pointed at its own LocalStack
# account and filtered to resources labelled platform.example.com/environment=<env>.
# On EKS (MODE=eks) each cluster is one environment and controllers use IRSA; that path
# is documented in CLAUDE.md / docs/design.md and is not exercised by this repo.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=platform/bootstrap/versions.env
source "$HERE/versions.env"
MODE="${MODE:-local}"
WHAT="${1:-all}"

# environment:account pairs hosted by this cluster (local: both; EKS: exactly one).
ENVIRONMENTS="${ENVIRONMENTS:-staging:111111111111 prod:222222222222}"
# ACK controllers installed per environment. RDS/EC2 are omitted locally because
# LocalStack Community does not provide RDS; they are listed for EKS.
if [[ "$MODE" == local ]]; then
  ACK_SERVICES="${ACK_SERVICES:-iam sqs dynamodb sns s3}"
else
  ACK_SERVICES="${ACK_SERVICES:-iam sqs dynamodb sns s3 rds ec2}"
fi

ack_version() {
  local v="ACK_$(echo "$1" | tr '[:lower:]' '[:upper:]')_VERSION"
  echo "${!v}"
}

install_kro() {
  echo "==> kro $KRO_CHART_VERSION"
  helm upgrade --install kro oci://registry.k8s.io/kro/charts/kro \
    --version "$KRO_CHART_VERSION" -n kro-system --create-namespace \
    -f "$HERE/values/kro.yaml" --wait --timeout 5m
}

install_ack() {
  local first=1 pair env account svc ns
  for pair in $ENVIRONMENTS; do
    env="${pair%%:*}"; account="${pair##*:}"; ns="ack-$env"
    kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    if [[ "$MODE" == local ]]; then
      # LocalStack maps a 12-digit access key ID to that account ID.
      kubectl -n "$ns" create secret generic ack-aws-credentials \
        --from-literal=credentials="$(printf '[default]\naws_access_key_id = %s\naws_secret_access_key = test\n' "$account")" \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    fi
    for svc in $ACK_SERVICES; do
      echo "==> ACK $svc $(ack_version "$svc") for $env (account $account)"
      local extra=()
      # CRDs are cluster-scoped: install them with the first environment only.
      [[ $first -eq 1 ]] || extra+=(--skip-crds)
      [[ "$MODE" == local ]] && extra+=(-f "$HERE/values/ack-local.yaml")
      # LocalStack only recognises virtual-hosted S3 requests on <bucket>.s3.<host>.
      [[ "$MODE" == local && "$svc" == s3 ]] && extra+=(--set aws.endpoint_url=http://s3.localstack:4566)
      helm upgrade --install "ack-$svc-$env" "oci://public.ecr.aws/aws-controllers-k8s/$svc-chart" \
        --version "$(ack_version "$svc")" -n "$ns" \
        --set "watchSelectors=platform.example.com/environment=$env" \
        --set "aws.region=us-east-1" \
        --set "deletionPolicy=delete" \
        "${extra[@]}" --wait --timeout 5m >/dev/null
    done
    first=0
  done
  # Locally, services LocalStack Community lacks get CRDs only (no controller), so every
  # RGD still type-checks and the chart can be exercised end to end where possible.
  for svc in ${ACK_CRD_ONLY_SERVICES:-$([[ "$MODE" == local ]] && echo "rds ec2")}; do
    echo "==> ACK $svc $(ack_version "$svc") CRDs only"
    helm show crds "oci://public.ecr.aws/aws-controllers-k8s/$svc-chart" --version "$(ack_version "$svc")" 2>/dev/null \
      | kubectl apply --server-side -f - >/dev/null
  done
}

install_rgds() {
  echo "==> kro ResourceGraphDefinitions"
  kubectl apply -f "$HERE/rgds/"
  local rgd
  for rgd in $(kubectl get rgd -o name); do
    kubectl wait "$rgd" --for=jsonpath='{.status.state}'=Active --timeout=120s
  done
}

install_observability() {
  echo "==> kube-prometheus-stack $KUBE_PROMETHEUS_STACK_VERSION (Prometheus + Grafana)"
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
  helm repo add grafana https://grafana.github.io/helm-charts >/dev/null
  helm repo update prometheus-community grafana >/dev/null
  helm upgrade --install kps prometheus-community/kube-prometheus-stack \
    --version "$KUBE_PROMETHEUS_STACK_VERSION" -n monitoring --create-namespace \
    -f "$HERE/values/kube-prometheus-stack.yaml" --wait --timeout 10m >/dev/null
  kubectl -n monitoring create configmap platform-dashboards \
    --from-file="$HERE/dashboards/" --dry-run=client -o yaml \
    | kubectl label --local -f - grafana_dashboard=1 -o yaml | kubectl apply -f - >/dev/null
  echo "==> Grafana Alloy $ALLOY_CHART_VERSION"
  helm upgrade --install alloy grafana/alloy --version "$ALLOY_CHART_VERSION" \
    -n monitoring -f "$HERE/values/alloy.yaml" --wait --timeout 5m >/dev/null
}

install_delivery() {
  local chart_repo="${CHART_REPO:-kind-registry:5000/charts}"
  local insecure="${CHART_REPO_INSECURE:-$([[ "$MODE" == local ]] && echo true || echo false)}"
  helm repo add argo https://argoproj.github.io/argo-helm >/dev/null
  helm repo update argo >/dev/null
  echo "==> Argo Rollouts $ARGO_ROLLOUTS_CHART_VERSION"
  helm upgrade --install argo-rollouts argo/argo-rollouts --version "$ARGO_ROLLOUTS_CHART_VERSION" \
    -n argo-rollouts --create-namespace -f "$HERE/values/argo-rollouts.yaml" --wait --timeout 5m >/dev/null
  echo "==> Argo CD $ARGOCD_CHART_VERSION"
  helm upgrade --install argocd argo/argo-cd --version "$ARGOCD_CHART_VERSION" \
    -n argocd --create-namespace -f "$HERE/values/argocd.yaml" --wait --timeout 10m >/dev/null
  echo "==> Argo CD projects + chart repository ($chart_repo)"
  for f in argocd-projects.yaml argocd-chart-repo.yaml; do
    CHART_REPO="$chart_repo" CHART_REPO_INSECURE="$insecure" \
      python3 -c 'import os,sys; print(os.path.expandvars(sys.stdin.read()))' < "$HERE/manifests/$f" \
      | kubectl apply -f - >/dev/null
  done
}

# ---- entrypoint -------------------------------------------------------------------------
case "$WHAT" in
  controllers) install_kro; install_ack; install_rgds ;;
  delivery) install_delivery ;;
  observability) install_observability ;;
  all) install_kro; install_ack; install_rgds; install_observability; install_delivery ;;
  *) echo "usage: $0 [all|controllers|delivery|observability]" >&2; exit 2 ;;
esac
echo "bootstrap ($WHAT, MODE=$MODE) complete"
