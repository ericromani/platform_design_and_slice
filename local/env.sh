# Source me: puts repo-local tools first on PATH and isolates helm/docker config
# from the user's global config (so a missing docker credential helper can't break OCI pulls).
_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
export PATH="$_ROOT/.tools/bin:$_ROOT/.venv/bin:/opt/podman/bin:$PATH"
export HELM_PLUGINS="$_ROOT/.tools/helm-plugins"
export HELM_REGISTRY_CONFIG="$_ROOT/.tools/registry.json"
export DOCKER_CONFIG="$_ROOT/.tools/docker"
export KIND_EXPERIMENTAL_PROVIDER="${KIND_EXPERIMENTAL_PROVIDER:-podman}"
export KUBECONFIG="$_ROOT/.tools/kubeconfig"
mkdir -p "$HELM_PLUGINS" "$DOCKER_CONFIG"
[[ -f "$HELM_REGISTRY_CONFIG" ]] || echo '{}' > "$HELM_REGISTRY_CONFIG"
[[ -f "$DOCKER_CONFIG/config.json" ]] || echo '{}' > "$DOCKER_CONFIG/config.json"
unset _ROOT
