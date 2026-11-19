---
name: decommission-service
description: >-
  Safely remove a service from the platform: inventory what it owns (Argo CD apps, kro
  instances, AWS queues/topics/tables/buckets/databases, IRSA role), decide with the
  developer what happens to its data, then remove it from staging before prod. Use for
  "decommission", "delete my service", "retire", "tear down", or cleaning up an
  abandoned service.
---

# Decommission a service

Removal is irreversible for anything deleted, so this skill is mostly about **inventory
and an explicit data decision**. Order is always staging first, then prod.

## 1. Inventory (read-only)

```bash
kubectl -n argocd get applications -l platform.example.com/service=<svc>
kubectl -n <svc>-staging get platformqueues,platformtopics,platformbuckets,platformtables,platformdatabases,platformworkloadidentities
```

From `deploy/values-prod.yaml`, list each data store with its `deletionPolicy` (DynamoDB,
S3 and RDS default to `retain`) and, for tables and DBs, `deletionProtection` (default
`true`; AWS refuses deletion). `--delete-data` lifts both and waits for AWS to confirm
before deleting. Ask the developer:
- Does anything still call this service or read its data? (Check for SNS subscribers and
  queue producers owned by other teams.)
- For each retained store: **keep** (default; it stays in AWS and is reported), **export
  then delete**, or **delete**?

## 2. Staging

```bash
.venv/bin/python platform/workflows/scripts/platform_deploy.py decommission --service <svc> --env staging
# add --delete-data only if the developer chose to delete data
```

Then confirm the namespace is gone and the IAM role no longer exists
(`python local/orders_traffic.py iam --env staging` should fail for the slice).

## 3. Prod (after staging succeeded, with explicit confirmation)

Same command with `--env prod`. The tool refuses prod while the staging Application
still exists. In CI, run the service's `decommission` workflow, which types the name as
confirmation and runs prod only after staging.

## 4. Report

What was deleted, and what was **retained** (the tool prints `RETAINED in AWS …`), with
the owner who must decide on it later. Suggest archiving the repo and removing its
`deploy.yaml` trigger.

## Known limitation (local only)

LocalStack Community lacks DynamoDB `GetResourcePolicy`, so ACK cannot finish deleting a
table with `--delete-data` locally. The tool times out and lists the stuck Table. On real
AWS this works. Locally, delete the table with the AWS CLI and clear the Table's finalizer.
