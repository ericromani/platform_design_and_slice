---
name: update-chart
description: >-
  Platform-team skill for changing the central microservice Helm chart or the kro RGDs
  behind it: add a values option or an AWS resource type, change defaults, or fix a
  template, schema-first, with helm-unittest coverage, the IAM least-privilege proof,
  a live RGD check, a version bump, and docs. Use for any edit under
  platform/charts/microservice or platform/bootstrap/rgds.
---

# Update the central chart / RGDs

Every service renders this chart, so treat each change as an API change.

## Steps

1. **Read** `platform/charts/microservice/CLAUDE.md` and, for AWS resources,
   `platform/bootstrap/CLAUDE.md`.
2. **Schema first**: add the field to `values.schema.json` with a `description`, tight
   types/enums/patterns and `additionalProperties: false`, then document the default in
   `values.yaml`, then change the template.
3. **New AWS resource type**: add an RGD (`platform/bootstrap/rgds/platform-<x>.yaml`)
   following the existing pattern:
   - the resource plus one `Policy` per resource;
   - the policy Resource wired from the resource's own status;
   - `readyWhen` on status, plus `ACK.ResourceSynced` for IAM kinds;
   - the environment label on everything;
   - `services.k8s.aws/deletion-policy` for data stores.
   Then add:
   - the kind to `aws-resources.yaml`, the identity's `resourceInstances`, the env-var
     injection in `_helpers.tpl`, and the Argo CD AppProject whitelist;
   - its ACK controller to `platform/bootstrap/install.sh` and Terraform's
     `platform-iam` (controller role + boundary actions).
4. **Tests**:
   - helm-unittest cases in `platform/charts/microservice/tests/`;
   - expected action sets in `tests/test_iam_least_privilege.py`;
   - a cookbook snippet in `.claude/skills/new-service/references/values-cookbook.md`
     (it is validated by `tests/test_cookbook.py`).
5. **Live check** (RGDs): `kubectl apply -f platform/bootstrap/rgds/<file>` and wait for
   `kubectl get rgd` to show `Active`; then deploy a service that uses it (`make demo` or a
   scratch values file) and confirm the kro instance reaches `ACTIVE`.
6. **Version**: bump `Chart.yaml` `version` (immutable once published); add a README
   changelog line; note any migration.
7. **Verify**: `make test`. Show the output, not a summary of it.

## Do not

- Do not loosen a schema constraint or an IAM action set to make a test pass.
- Do not bundle a chart change with unrelated template, workflow or infra edits.
