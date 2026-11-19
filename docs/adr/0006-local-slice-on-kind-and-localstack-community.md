# 0006: Local slice on kind + LocalStack Community, one cluster for both environments

**Status:** accepted

## Context
The slice must run on a laptop (a Podman VM of about 8 GiB) without AWS accounts or
licences.

## Decision
- kind stands in for EKS, and one cluster hosts both environments (namespaces
  `<svc>-<env>`, two AppProjects).
- LocalStack Community stands in for AWS, with one account per environment; each
  environment gets its own ACK controller set selected by label.
- IRSA is emulated by the chart injecting the webhook's env and token in local mode.

## Consequences
- Same chart, RGDs, deploy CLI and Alloy config as production. Differences are switches
  in `global` and bootstrap values, not forks.
- IAM is not enforced locally, so least privilege is proven statically
  (`tests/test_iam_least_privilege.py`) and inspected live (`make iam`).
- No RDS and no load balancer controller locally; these are covered by chart unit tests.
- A LocalStack gap (DynamoDB `GetResourcePolicy`) blocks local data deletion through ACK.

## Alternatives considered
- LocalStack Pro (EKS emulation, IAM enforcement): higher fidelity, requires a licence.
- Two kind clusters: closer to production, about twice the memory.
