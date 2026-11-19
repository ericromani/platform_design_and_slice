# 0003: Argo Rollouts canary + Prometheus analysis as the deploy gate

**Status:** accepted

## Context
Deploys must be validated by health signals (probes plus metrics from Alloy), and rolled
back automatically on failure.

## Decision
The chart renders an Argo Rollout with `workloadRef` to a zero-replica Deployment (the
pod template stays a standard Deployment), canary steps, and an AnalysisTemplate querying
Prometheus for the canary pods only (by `rollouts_pod_template_hash`). On analysis
failure the Rollout aborts in-cluster. The deploy CLI also re-applies the last good
Application, so Argo CD's desired state matches what runs, and fails the job.

## Consequences
- Rollback does not depend on the CI runner surviving.
- Every service must emit the metrics contract; presets do.
- Each deploy stamps a unique `releaseId` on the pod template so the gate always tracks a
  new revision, even for config-only changes.
- Basic canary uses replica ratios; traffic-weighted canaries need a mesh/ALB integration
  later.

## Alternatives considered
- Pipeline-driven gate (plain Deployment, CI queries Prometheus, CI rolls back): simpler,
  but the rollback depends on the pipeline and there is no in-cluster abort.
