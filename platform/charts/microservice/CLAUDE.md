# microservice chart — agent guide

The one chart every service deploys with. Platform-team owned, versioned, published to the
OCI registry (`publish_chart.sh`). Service repos never fork it; they supply a values file.

## Read first

- `values.schema.json` is the **contract** (strict: `additionalProperties: false`
  everywhere). If a field is not in the schema, it does not exist.
- `values.yaml` holds the documented defaults; `README.md` is the human reference.
- `ci/full-values.yaml` exercises every feature (lint + kubeconform use it).
- `tests/*_test.yaml` are helm-unittest suites; `tests/values/base.yaml` is their fixture.

## What the chart renders (and why)

| Template | Renders | Note |
|---|---|---|
| `deployment.yaml` | Deployment, `replicas: 0` | Pod-template holder for the Rollout (`workloadRef`); never runs pods, so it never fights the Rollout or Argo CD self-heal |
| `rollout.yaml` | Argo Rollout | Canary steps from `rollout.canaryWeights`, analysis after each step, `progressDeadlineAbort` |
| `analysistemplate.yaml` | AnalysisTemplate | Prometheus queries on canary pods only (`rollouts_pod_template_hash`) |
| `serviceaccount.yaml` | ServiceAccount | IRSA annotation when the service declares AWS resources |
| `aws-resources.yaml` | kro instances (`PlatformQueue`, `PlatformTable`, …) | sync-wave **-2** |
| `workload-identity.yaml` | `PlatformWorkloadIdentity` | sync-wave **-1**: the role is created only after every policy exists (ACK otherwise backs off for minutes) |
| `loadbalancer.yaml` | ALB Ingress / NLB Service | AWS Load Balancer Controller; refused in local mode |
| `service.yaml`, `hpa.yaml`, `pdb.yaml` | the usual | HPA targets the Rollout |

`global.*` is injected by the deploy pipeline from Terraform outputs. Developers must not
set it; `platform_deploy.py validate` rejects files that do.

## Changing the chart

1. Schema first: add or change the field in `values.schema.json` (with a description),
   then `values.yaml` (documented default), then the template.
2. If the change touches a kro kind, change the RGD in `platform/bootstrap/rgds/` in the
   same PR and keep field names identical on both sides.
3. Add or adjust a helm-unittest case. For a new AWS resource type, also extend
   `tests/test_iam_least_privilege.py` with its exact action sets.
4. Bump `version` in `Chart.yaml` (published versions are immutable). Breaking contract
   changes need a minor bump plus a migration note in `README.md`.
5. Run `make test-chart` (lint, unittest, kubeconform) and `make test`.

## Pitfalls already paid for

- YAML 1.1 reads a bare `N`/`Y` as a boolean. DynamoDB key types are therefore spelled
  `string|number|binary` in values, and the template `quote`s the `S/N/B` it emits.
- Helm's schema validator uses Go RE2: no lookahead. Use `not: {pattern: …}` instead.
- Argo Rollouts' `{{args.x}}` collides with Helm templating; keep it inside a Helm string
  literal (see `analysistemplate.yaml`).
- Every deploy stamps `global.releaseId` on the pod template, so each deploy is a distinct
  release the gate can track, even when only configuration changed.
