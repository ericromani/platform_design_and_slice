# 0002: The chart renders kro instances; kro composes ACK resources

**Status:** accepted

## Context
A queue needs the queue, a scoped IAM policy, tags and encryption. The policy needs the
queue's ARN, which only exists after creation. The chart cannot see AWS state.

## Decision
Platform RGDs (`PlatformQueue`, `PlatformTable`, `PlatformTopic`, `PlatformBucket`,
`PlatformDatabase`, `PlatformWorkloadIdentity`) are installed cluster-wide by bootstrap
and versioned with the chart. The chart renders instances; kro creates the ACK resources
and wires status (ARNs) into dependent resources. RGDs are cluster-scoped, so they live
in bootstrap rather than in each release (two releases would fight over ownership).

## Consequences
- Platform can evolve a resource's internals without a chart release.
- IAM policies reference real ARNs, and the role references only its siblings' policies.
- Uses kro alpha features (`omit()` behind `CELOmitFunction`) for fields that must be
  absent; pinned kro version, revisit on upgrade.
- Readiness must be modelled carefully (`ACK.ResourceSynced` for IAM; sync waves for
  role-after-policies).

## Alternatives considered
- Chart renders ACK directly with deterministic ARNs: works, but couples the chart to
  every ACK field and leaks composition into each release.
- Crossplane compositions: equivalent power, heavier footprint; kro is Kubernetes-native
  and ACK is AWS-maintained.
