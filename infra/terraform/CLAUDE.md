# infra/terraform — agent guide

The **prerequisite** every deploy depends on, owned by the platform team and applied with
Terraform, never by service pipelines: one VPC + EKS cluster + platform IAM per
environment. Developers never edit this.

## Layout

- `modules/vpc` covers public/private subnets across AZs, NAT, LB discovery tags, and the
  DB subnet group.
- `modules/eks` covers the cluster, the managed node group, the IRSA OIDC provider and
  access entries.
- `modules/platform-iam` covers:
  - the **workload permissions boundary**;
  - IRSA roles for the ACK controllers (the IAM controller may only create roles carrying
    the boundary and can never remove one);
  - the GitHub OIDC deploy role.
- `modules/environment` composes the above and publishes the chart `global` values to
  SSM `/platform/<env>/chart-globals` (the deploy pipeline reads it).
- `envs/staging`, `envs/prod` are real AWS roots (S3 backend, `allowed_account_ids`).
  They are validated, not applied, in this repo.
- `envs/local` applies the same `vpc` and `platform-iam` modules to two LocalStack
  accounts (staging 111111111111, prod 222222222222). kind replaces EKS: the OIDC
  provider points at kind's issuer. It writes `local/generated/<env>-globals.yaml`.

## Working here

- `terraform fmt -recursive`, then `terraform validate` in every root you touched
  (`make test-terraform` does all of them with `-backend=false`).
- Local apply: `make infra` (idempotent). Changing a module affects real envs too, so
  keep LocalStack-only switches as module variables (`enable_nat_gateway`,
  `create_db_subnet_group`), not forks.
- Widening the permissions boundary is a security review, not a fix. If a new RGD needs a
  new action, add it to the boundary and to `tests/test_iam_least_privilege.py`
  deliberately, in the same PR as the RGD.
- Lock files (`.terraform.lock.hcl`) are committed. State files never are.
