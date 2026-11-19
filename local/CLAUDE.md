# local — agent guide

The local stand-in for AWS. Everything runs on the Podman machine:
- **kind** cluster `platform` (EKS stand-in; one cluster hosts staging and prod);
- **LocalStack** container `localstack` (AWS; each environment is a separate account);
- an OCI **registry** `kind-registry` (ECR stand-in; host port 5001).

## Lifecycle

```bash
make tools      # once: repo-local CLIs + .venv (local/install-tools.sh)
make up         # local/up.sh + platform/bootstrap/install.sh all + make infra
make demo       # every journey end to end (see Makefile targets for single steps)
make down       # local/down.sh: delete the cluster and containers
```

`local/env.sh` (sourced by the Makefile) isolates the session: kubeconfig lives in
`.tools/kubeconfig` (the user's real clusters are never touched), and Helm and Docker
config are repo-local.

## Helpers

- `orders_traffic.py send|verify|iam` sends orders, checks DynamoDB, and prints the
  service role's live policies.
- UIs: Argo CD http://localhost:8080 (`admin`, password from
  `kubectl -n argocd get secret argocd-initial-admin-secret`), Grafana
  http://localhost:3000 (admin/admin), Prometheus http://localhost:9090.

## Troubleshooting

- Pods cannot reach `localstack`: re-run `local/up.sh` (it re-applies the CoreDNS rewrite
  and checks reachability from a pod).
- A kro instance stays `IN_PROGRESS`: `kubectl get <ack-kind> -n <ns> -o yaml` and read the
  `ACK.Recoverable`/`ACK.Terminal` condition, which names the failing AWS call.
- Memory: the full stack needs about 6 GiB in the Podman VM (`podman machine set --memory 8192`).
