# platform workflows — agent guide

This directory is the root of the **`platform-workflows`** repository: the reusable GitHub
Actions every service repo calls (`.github/workflows/*.yaml`) and the deploy CLI they run
(`scripts/platform_deploy.py`). Service repos keep three thin callers (`ci.yaml`,
`deploy.yaml`, `decommission.yaml` in each preset) and never re-implement build or deploy.

## Workflows

| Workflow | Called by | Does |
|---|---|---|
| `build-{python,go,java}.yaml` | service `ci.yaml` / `deploy.yaml` | lint + unit → integration (LocalStack service container) → deploy contract → image |
| `validate-deploy.yaml` | the builds | `platform_deploy validate` + render + kubeconform for staging and prod values |
| `build-image.yaml` | the builds | Docker build; on main, push to ECR tagged with the short SHA |
| `deploy.yaml` | service `deploy.yaml` | **staging only**: Argo sync, rollout gate, auto-rollback, staging verification record |
| `promote.yaml` | service `deploy.yaml` | `check-verified` (staging credentials) → prod deploy (`production` environment) |
| `decommission.yaml` | service `decommission.yaml` | staging, then prod (job dependency), retained data reported |

`.github/actions/setup-platform` installs the CLI from **the same ref** as the calling
workflow (via `github.action_path`), so scripts and workflows cannot drift. Consumers pin
`@v1`; release by moving the `v1` tag only after `make test` and `make demo` pass.

## The deploy CLI (`scripts/platform_deploy.py`)

One implementation for CI and laptops (`make deploy-staging` runs the same commands).
Subcommands: `validate`, `render`, `deploy`, `promote`, `check-verified`, `decommission`.

- The release gate (`wait_for_release`) is green only when Argo CD is Synced and Healthy, the
  Deployment carries the new tag, the Rollout's pod-template hash has moved off the
  pre-deploy hash, and the Rollout is Healthy with stable == current. On abort it reads
  the failed AnalysisRun, re-applies the last good Application, and exits 1.
- A release is recorded as verified only after a Successful AnalysisRun for its exact pod
  hash. First revisions get a CLI-run verification analysis.
- `deploy --env prod` is refused unless called by the promote pipeline. The real
  enforcement is IAM: deploy roles trust only these reusable workflows (`job_workflow_ref`),
  and prod trusts only `promote.yaml` and `decommission.yaml`. Promotion also requires the
  chart version staging verified, and in CI `service.name` must equal the repo name.
- Unit tests: `tests/test_platform_deploy.py`. Behavioural changes need an e2e run
  (`make demo`) as well.

## Rules

- Never interpolate `${{ inputs.* }}` into `run:`; pass it through `env:` (script injection).
- Credentials come only from GitHub OIDC → `vars.PLATFORM_*_ROLE_ARN` per GitHub
  environment. No static keys, no `secrets.AWS_*`.
- Pin third-party actions to a major version; verify downloaded binaries by checksum.
- `actionlint` must pass (`make test`).
