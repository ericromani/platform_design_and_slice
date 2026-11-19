# 0005: Data stores are retained on decommission by default

**Status:** accepted

## Context
Deleting an Argo CD Application cascades to AWS through kro and ACK. A mistaken deletion
must not destroy data.

## Decision
DynamoDB, S3 and RDS instances carry `services.k8s.aws/deletion-policy: retain` unless
the service sets `deletionPolicy: delete`. Queues, topics, policies and roles are deleted.
Decommission reports retained stores; `--delete-data` flips them explicitly first.

## Consequences
- Accidental deletions are recoverable; deliberate cleanup is a visible second step.
- Retained stores need an owner decision (the decommission skill asks for one).
