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
- Promotion is keyed on the image tag; staging and prod values can still differ (replicas,
  canary steps). `validate` and review cover prod-only differences.
