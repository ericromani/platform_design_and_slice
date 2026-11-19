#!/usr/bin/env bash
# Installs pinned CLI tools into ./.tools/bin (repo-local, gitignored) and verifies
# every download against its published checksum. Nothing is installed system-wide.
# Source local/env.sh afterwards (the Makefile does this for you).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/.tools/bin"
DL="$ROOT/.tools/dl"
mkdir -p "$BIN" "$DL"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"   # darwin | linux
ARCH="$(uname -m)"
case "$ARCH" in x86_64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; esac

KIND_VERSION="v0.33.0"
HELM_VERSION="v3.22.1"
KUBECONFORM_VERSION="v0.8.0"
ACTIONLINT_VERSION="1.7.12"

cd "$DL"

if [[ ! -x "$BIN/kind" ]]; then
  echo "==> kind $KIND_VERSION"
  curl -fsSLO "https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-${OS}-${ARCH}"
  curl -fsSLO "https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-${OS}-${ARCH}.sha256sum"
  shasum -a 256 -c "kind-${OS}-${ARCH}.sha256sum"
  install -m 755 "kind-${OS}-${ARCH}" "$BIN/kind"
fi

if [[ ! -x "$BIN/helm" ]]; then
  echo "==> helm $HELM_VERSION"
  curl -fsSLO "https://get.helm.sh/helm-${HELM_VERSION}-${OS}-${ARCH}.tar.gz"
  curl -fsSLO "https://get.helm.sh/helm-${HELM_VERSION}-${OS}-${ARCH}.tar.gz.sha256sum"
  shasum -a 256 -c "helm-${HELM_VERSION}-${OS}-${ARCH}.tar.gz.sha256sum"
  tar xzf "helm-${HELM_VERSION}-${OS}-${ARCH}.tar.gz"
  install -m 755 "${OS}-${ARCH}/helm" "$BIN/helm"
fi

if [[ ! -x "$BIN/kubectl" ]]; then
  KV="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"
  echo "==> kubectl $KV"
  curl -fsSLO "https://dl.k8s.io/release/${KV}/bin/${OS}/${ARCH}/kubectl"
  echo "$(curl -fsSL "https://dl.k8s.io/release/${KV}/bin/${OS}/${ARCH}/kubectl.sha256")  kubectl" | shasum -a 256 -c
  install -m 755 kubectl "$BIN/kubectl"
fi

if [[ ! -x "$BIN/kubeconform" ]]; then
  echo "==> kubeconform $KUBECONFORM_VERSION"
  curl -fsSLO "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/kubeconform-${OS}-${ARCH}.tar.gz"
  curl -fsSLO "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/CHECKSUMS"
  grep "kubeconform-${OS}-${ARCH}.tar.gz" CHECKSUMS | shasum -a 256 -c
  tar xzf "kubeconform-${OS}-${ARCH}.tar.gz" -C "$BIN" kubeconform
fi

if [[ ! -x "$BIN/actionlint" ]]; then
  echo "==> actionlint $ACTIONLINT_VERSION"
  F="actionlint_${ACTIONLINT_VERSION}_${OS}_${ARCH}.tar.gz"
  curl -fsSLO "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/${F}"
  curl -fsSLO "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_checksums.txt"
  grep " ${F}\$" "actionlint_${ACTIONLINT_VERSION}_checksums.txt" | shasum -a 256 -c
  tar xzf "$F" -C "$BIN" actionlint
fi

# shellcheck source=local/env.sh
source "$ROOT/local/env.sh"
if ! helm plugin list | grep -q '^unittest'; then
  echo "==> helm-unittest plugin"
  helm plugin install https://github.com/helm-unittest/helm-unittest
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  echo "==> python venv (.venv) for platform scripts and tests"
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements-dev.txt"
fi

echo "tools ready in $BIN"
