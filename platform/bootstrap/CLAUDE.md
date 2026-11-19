# platform bootstrap — agent guide

Everything installed **once per cluster** before any service deploys: kro + the platform
RGDs, ACK controllers, Argo CD (+ AppProjects, chart repo), Argo Rollouts, and the
observability stack. `install.sh [all|controllers|delivery|observability]` is idempotent.

## Layout

- `versions.env` pins every add-on. One version bump per PR; re-run `install.sh` locally
  and `make demo` before proposing it.
- `values/*.yaml` are per-add-on Helm values. `ack-local.yaml` points ACK at LocalStack.
- `rgds/` holds the kro ResourceGraphDefinitions behind the chart's AWS options. They are
  versioned **in lockstep with the chart** (the chart renders their kinds).
- `manifests/` holds the Argo CD AppProjects (guardrails) and the chart repository secret.
- `dashboards/` holds Grafana dashboards, loaded by the sidecar from a ConfigMap.

## How environments map to controllers

- **EKS**: one cluster per environment. ACK controllers use IRSA roles from
  `infra/terraform/modules/platform-iam` (the IAM controller may only create roles that
  carry the workload permissions boundary).
- **Local**: one kind cluster hosts both environments. Each environment gets its own set
  of ACK controllers (`ack-staging`, `ack-prod`) with `watchSelectors` on the label
  `platform.example.com/environment=<env>`, pointed at its own LocalStack account (the
  12-digit access key ID selects the account).

## Editing RGDs

- kro type-checks templates against the ACK CRD schemas when you apply the RGD. Always
  `kubectl apply -f rgds/<file>` and `kubectl get rgd` until it shows `Active` before
  you trust a change.
- Quote any CEL scalar that contains `: ` (ternaries, map literals), or YAML parsing breaks.
- Use `omit()` (feature gate `CELOmitFunction`, enabled in `values/kro.yaml`) for fields
  that must be absent rather than empty.
- `readyWhen` for IAM resources must require `ACK.ResourceSynced=True`, not just an ARN,
  because ACK attaches policies on a later reconcile than the one that creates the role.
- Every ACK resource must carry the `platform.example.com/environment` label, or no
  controller will reconcile it.
- Any policy change must keep `tests/test_iam_least_privilege.py` green; add expected
  action sets there for new access levels.

## Argo CD

- `values/argocd.yaml` adds a Lua health check for every `kro.run/*` kind (Healthy only
  when the instance is `ACTIVE`). With the chart's sync waves, pods start only after their
  AWS resources and role exist.
- AppProjects whitelist exactly the kinds the chart renders. Adding a kind to the chart
  means adding it here too.

## Local quirks (LocalStack Community)

- S3 needs `endpoint_url=http://s3.localstack:4566` (virtual-hosted style) and a separate
  `identity_endpoint_url`; CoreDNS rewrites `*.localstack` (see `local/up.sh`).
- DynamoDB `GetResourcePolicy` is unimplemented, so ACK cannot finish *deleting* a table
  locally (see README "Known limitations"). Table readiness uses `tableStatus` instead of
  `ResourceSynced` for the same reason.
