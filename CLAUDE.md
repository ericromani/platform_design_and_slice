# Developer platform — agent guide (start here)

This repo is an **agentic-first developer platform**: a design plus a runnable local
vertical slice (kind + LocalStack) where a service goes from "new repo" to "running in
prod" in under a day. Each top-level directory stands in for a **separate repository** in
the real platform.

This file is a router. Load only the guide for the area you are touching: Claude Code
pulls in a directory's `CLAUDE.md` automatically when you work there; read it explicitly
when planning. Do not read every guide up front.

## Where things live

| You are working on… | Read | Stands in for repo |
|---|---|---|
| Architecture, diagrams, decisions (ADRs) | `docs/CLAUDE.md` | platform docs |
| VPC / EKS / platform IAM (prerequisite infra) | `infra/terraform/CLAUDE.md` | `platform-infra` |
| Cluster add-ons, kro RGDs, Argo CD, observability | `platform/bootstrap/CLAUDE.md` | `platform-bootstrap` |
| The central Helm chart + its values schema | `platform/charts/microservice/CLAUDE.md` | `platform-charts` |
| Central GitHub Actions + the deploy CLI | `platform/workflows/CLAUDE.md` | `platform-workflows` |
| Language presets (python / go / java) | `templates/CLAUDE.md` | template repos |
| Creating a service repo from a preset | `scaffold/CLAUDE.md` | (scaffolder) |
| The example service (vertical slice) | `examples/orders-service/CLAUDE.md` | a service repo |
| Running the local cloud | `local/CLAUDE.md` | (dev tooling) |
| Repo-level tests (IAM proof, deploy CLI, scaffold) | `tests/CLAUDE.md` | — |

## Developer journeys → skills

| Journey | Skill | What it does |
|---|---|---|
| New service | `/new-service` | Interviews the developer, scaffolds the repo, writes and validates `deploy/values-*.yaml` |
| Update a service (code or resources) | `/new-service` (update mode) | Edits the `aws:` block / settings of an existing values file and validates it |
| Promote staging → prod | `/promote-service` | Checks the staging verification, runs the promotion |
| Decommission | `/decommission-service` | Inventories retained data, runs staging-then-prod removal |
| Change the chart / RGDs (platform team) | `/update-chart` | Schema-first change with tests and a version bump |

## The contracts everything hangs on

1. **Values contract**: `platform/charts/microservice/values.schema.json`. A developer
   values file must validate (`make validate`) before any deploy. `global` is pipeline-only.
2. **Health contract**: services serve `/healthz` (liveness), `/readyz` (readiness) and
   `/metrics` (Prometheus) and declare them in the values file.
3. **Metrics contract**: `http_requests_total{method,path,status}`,
   `app_work_items_total{outcome=success|failure|rejected}`, `app_work_duration_seconds`.
   Rollout analysis gates canaries on these.
4. **Promotion contract**: prod only accepts image tags with a staging verification record
   (`/platform/promotions/<service>/<tag>` in SSM), written after a healthy canary.

## Rules for agents working here

- Keep changes scoped to the area you were asked about; a chart change, an RGD change and a
  template change are separate PRs unless the task is explicitly cross-cutting.
- Contract changes (schema, metric names, health paths, RGD kinds/fields) are breaking for
  every service: bump the chart version, update RGDs in lockstep, update presets and docs.
- Never weaken IAM to make something work: `tests/test_iam_least_privilege.py` must pass.
- Verify before you claim done: `make test` (static, no cluster) and, when the change
  affects runtime behaviour, the e2e targets in `local/CLAUDE.md`.
- Secrets never go in values files or the repo; locally everything uses LocalStack's fake
  keys, in CI everything uses GitHub OIDC roles.

## Quick commands

```bash
make tools        # repo-local CLIs into .tools/ (kind, helm, kubectl, kubeconform, actionlint)
make test         # all static checks: lint, chart unit tests, schema, IAM proof, presets
make up           # local cloud + bootstrap + Terraform prerequisite
make demo         # journeys end to end: deploy, update, rollback, promote, decommission
make down         # tear everything down
```
