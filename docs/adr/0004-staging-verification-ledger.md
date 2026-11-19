# 0004: Prod accepts only image tags verified in staging

**Status:** accepted

## Context
"Deploy to staging first and validate it" must be enforced, not encouraged.

## Decision
After a release passes the gate in staging, the deploy CLI writes
`/platform/promotions/<service>/<tag>` to SSM in the staging account, with time, chart
version and values hash. `promote.yaml` checks the record in a job holding only staging
credentials, then deploys prod in a separate job in the `production` GitHub environment.
`deploy --env prod` is refused outside that pipeline.

## Consequences
- A tag that never passed staging cannot reach prod, even on a re-run.
- The ledger doubles as an audit trail (kept on decommission).
- Promotion is keyed on the image tag (ECR tags are immutable) plus the chart version.
  Staging and prod values can still differ (replicas, canary steps); `validate` and review
  cover prod-only differences.
- The guarantee rests on IAM, not on CLI flags. Deploy roles trust only the platform's
  reusable workflows (`job_workflow_ref`), prod trusts only promote and decommission, and
  only the staging role can write the ledger.
- Verification requires a Successful AnalysisRun of the exact pod hash. First revisions,
  where Rollouts skips the canary, get a CLI-run verification analysis.
