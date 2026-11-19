# 0001: One central chart with a strict values schema

**Status:** accepted

## Context
Teams need Kubernetes workloads plus AWS resources without each team learning Helm, IAM
and the AWS APIs, and without drifting into per-team chart forks.

## Decision
One platform-owned `microservice` chart, published as immutable versions to an OCI
registry. Its `values.schema.json` is strict (`additionalProperties: false`) and is the
only interface. Service repos hold `deploy/values-<env>.yaml`; the pipeline injects
`global` from Terraform outputs.

## Consequences
- Typos and unsupported options fail in the PR (`validate-deploy.yaml`), not in a cluster.
- Agents have a precise target: the schema plus the cookbook.
- Every new capability is a chart release; the platform team is on the critical path for
  new resource types. That is deliberate, because new resource types need IAM review.

## Alternatives considered
- Per-service charts or Kustomize: maximum flexibility, but no guardrails and N copies.
- Raw ACK manifests in service repos: exposes AWS details and lets services write IAM.
