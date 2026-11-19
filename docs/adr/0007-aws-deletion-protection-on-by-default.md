# 0007: AWS deletion protection on by default for tables and databases

**Status:** accepted (extends [0005](0005-retain-data-stores-by-default.md))

## Context
ADR 0005 retains data stores when Kubernetes deletes them (`deletionPolicy: retain`).
That guards one path only. A store can still be deleted by a person or a script holding
AWS credentials, or by a values change that flips `deletionPolicy` before a removal.
RDS had AWS deletion protection only in prod; DynamoDB had none.

## Decision
- `aws.dynamodb[].deletionProtection` and `aws.rds[].deletionProtection` default to
  `true` in **every** environment. The RGDs set `deletionProtectionEnabled` (DynamoDB)
  and `deletionProtection` (RDS).
- `validate` rejects `deletionPolicy: delete` unless `deletionProtection: false` is set
  too. Otherwise AWS would refuse the delete Kubernetes requested, and decommission would
  hang.
- `decommission --delete-data` lifts both guards, waits until ACK reports the change
  synced to AWS for that generation, and only then deletes. If it cannot confirm, it
  stops without deleting anything.
- S3 has no bucket-level deletion-protection setting. Buckets rely on `retain` (and AWS
  refusing to delete non-empty buckets); enable `versioning` for object-level recovery.

## Consequences
- Deleting data now always takes two deliberate steps.
- Disposable stores (caches, scratch tables) must say so explicitly with both fields.
- Staging RDS instances are protected too, so tearing staging down takes the same
  explicit path as prod.
