# Proposed next steps

Proposals, not yet built. Each section has the same parts:
- **Today** (what the repo already does);
- **Gap**;
- **Proposal** (concrete design);
- **Done when** (the check that proves it).
The suggested order is at the end.

## 1. IAM guardrails: no broad permissions, ever

**Today.**
- Service policies come only from the RGDs, with fixed action sets per access level.
- Each policy's Resource is wired from that resource's own ARN.
- `tests/test_iam_least_privilege.py` checks this statically, and every role carries
  `platform-workload-boundary`.

**Gap.**
- The guarantee is a test over *our* RGD sources only. Nothing rejects a broad policy
  arriving another way: a new RGD, a Terraform change, or an ACK `Policy` applied
  directly.
- The boundary itself is broader than it should be: `sqs:*` on `Resource: "*"`.

**Proposal: three layers, each sufficient alone.**
1. **In the PR** (platform repos): a policy linter run in CI over every IAM document we
   can produce:
   - the RGD policy templates;
   - the `terraform show -json` plan output of `infra/terraform`;
   - the chart's rendered policies.
   It rejects any `Action` containing `*`, any `Resource: "*"`, any `NotAction` /
   `NotResource`, and any statement without a concrete ARN. A short, documented
   allowlist covers the unavoidable cases (`table/<name>/index/*`, `bucket/<name>/*`).
   Run `aws accessanalyzer validate-policy` and `check-no-new-access` against the
   previous release as well.
2. **In the cluster**: a Kyverno (or Gatekeeper) admission policy on
   `iam.services.k8s.aws/Policy` and `Role`. It parses `policyDocument`, `inlinePolicies`
   and `policies` with the same rules, so a broad document cannot be applied, even by a
   cluster admin, outside a break-glass exception.
3. **In AWS**:
   - replace the boundary's `sqs:*` with the explicit data-plane actions;
   - add an SCP that denies `iam:CreatePolicy` / `iam:CreatePolicyVersion` /
     `iam:PutRolePolicy` for documents with wildcard actions (via `iam:PolicyDocument`
     conditions where available; otherwise restrict those actions to the ACK IAM
     controller role, whose documents layer 2 has already vetted);
   - put CODEOWNERS on `platform/bootstrap/rgds/` and `modules/platform-iam`, so a new
     access level always needs a platform-security review.

**Done when** a PR adding `s3:*` on `*` anywhere fails CI, the same document applied with
`kubectl` is rejected by admission, and the boundary contains no wildcard actions.

## 2. Mandatory peer review before production

**Today.**
- Prod is reachable only through `promote.yaml`, for staging-verified tags.
- The `production` GitHub environment *can* require reviewers, but it's optional and set
  per repo.

**Gap.** A single developer can author, merge and ship to prod.

**Proposal.**
1. **Org-level repository ruleset**, applied to every repo with the `platform-service`
   topic (the scaffolder sets the topic). On `main`:
   - pull request required, with at least 1 approval from someone other than the author;
   - stale approvals dismissed on new commits;
   - the code-owner review required;
   - required status check: `ci / build`;
   - no direct pushes or force pushes, and no bypass except a break-glass team.
2. **`production` environment required reviewers**, with "prevent self-review",
   provisioned by Terraform (`github_repository_environment`) when the service is
   created, so it isn't left to each team.
3. **Belt and braces in `promote.yaml`**:
   - before deploying, look up the commit's merged PR (`gh api
     repos/{repo}/commits/{sha}/pulls`) and fail unless it has an approving review from
     someone other than the PR author and the commit pusher;
   - record the approver in the staging verification ledger, for audit.

**Done when** a self-approved, or unreviewed, change cannot reach prod, and the ledger
shows who approved each prod release.

## 3. PagerDuty and Grafana alerting, created with the service

**Today.**
- Metrics flow (Alloy → Prometheus/Grafana Cloud) and a shared dashboard exists.
- There are no alert rules and no on-call routing.

**Gap.** A new service can go live with nobody paged when it breaks.

**Proposal.**
1. **New-service input**: `/new-service` requires a **PagerDuty service** owned by the
   team (ID or name). The skill checks that it exists and belongs to the team via the
   PagerDuty API. It cannot finish without one. The ID goes into
   `deploy/values-*.yaml` as `service.oncall.pagerdutyService`, validated by the schema.
2. **Terraform-managed alerting** in a central `service-alerting` root (one small YAML
   per service, opened as a PR by the skill and applied by the platform's Terraform CI),
   using the `grafana` and `pagerduty` providers:
   - `pagerduty_service_integration` (Events API v2) on the team's service;
   - `grafana_contact_point` with that integration key;
   - a `grafana_notification_policy` route matching `service=<name>`;
   - a `grafana_rule_group` from platform templates, built on the metrics contract:
     - availability (`up` == 0 / no ready pods);
     - work failure ratio and 5xx ratio above the rollout thresholds for 5 minutes;
     - p95 latency above the SLO;
     - no work processed while the queue is non-empty (`ApproximateAgeOfOldestMessage`
       via CloudWatch);
     - rollout aborted.
   Teams can add rules; they can't remove the baseline ones.
3. **Routing by environment**: prod alerts page at high urgency; staging alerts go
   low-urgency to the same team.
4. **Decommission** deletes the rule group and contact point (the integration is kept for
   history).

**Done when** creating a service creates its alert rules and contact point, a broken
release in staging opens a low-urgency PagerDuty incident for the owning team, and a prod
outage pages them.

## 4. Autoscaling is mandatory (HPA or KEDA)

**Today.** `autoscaling.enabled` defaults to `false`; a fixed `replicas` count is allowed.

**Gap.** Services can ship without any scaling, and kind has no metrics-server, so CPU
HPAs don't work locally.

**Proposal.**
1. **Schema**: replace `replicas` with a required `scaling` block. Its `type` is one of:
   - `hpa`: CPU and/or memory targets, with `minReplicas` / `maxReplicas`;
   - `keda`: event-driven.
   Validation rejects `maxReplicas <= minReplicas`, and requires `minReplicas >= 2` in
   prod (with the PDB) so a single pod is never the whole service.
2. **KEDA** in bootstrap, with a default trigger derived from the service's own
   resources: a `consume` queue automatically gets an `aws-sqs-queue` trigger
   (`identityOwner: workload`, so it uses the service's IRSA role, which already has
   `GetQueueAttributes`). HTTP services get a CPU or `prometheus` (request-rate) trigger.
   The `ScaledObject` / HPA targets the Rollout, which already supports scaling.
3. **Bootstrap**: metrics-server everywhere (including kind) so the HPA path works in
   the slice.
4. The `new-service` skill asks about load shape (steady, spiky, queue-driven) and picks
   the scaling type.

**Done when** a values file without scaling fails validation, the orders-service scales
on queue depth in the local slice, and the load-test demo shows replicas rising and
falling.

## 5. Application logs shipped to an external store, built in

**Today.** Logs stay in the pods (`kubectl logs`). Alloy ships metrics only.

**Gap.** There is no retention, no search across pods or versions, and nothing to alert
on from logs.

**Proposal.**
1. **Collection**: extend the existing Alloy config with `loki.source.kubernetes` for
   every pod carrying the platform labels. It adds the same labels as the metrics
   (`service`, `environment`, `version`, `team`, `rollouts_pod_template_hash`) and
   writes to Grafana Cloud Loki in production (or CloudWatch Logs / OpenSearch,
   depending on the org standard). In the slice it writes to an in-cluster Loki with a
   Grafana datasource.
2. **Log contract**: JSON lines with `level`, `msg`, `service`, `version`, `trace_id`
   (and `order_id`-style domain keys at the service's discretion). Presets emit this by
   default (Python `logging` JSON formatter, Go `slog` JSON, Spring Boot structured
   logging).
3. **Safety**: an Alloy stage that drops or masks fields matching secret and PII patterns
   before data leaves the cluster. Retention is set per environment (for example 7 days
   staging, 30 days prod).
4. **Use it**:
   - the service dashboard gets a logs panel filtered to the service;
   - alert templates (section 3) gain an "error log rate" rule;
   - a failed rollout's report links to the canary's logs.

**Done when** a new service's logs are searchable in Grafana within a minute of deploy
without the team configuring anything, and a test record containing a fake secret arrives
masked.

## 6. Move the skills to a shared AI vault

**Today.** The skills live in this repo's `.claude/skills/`, and they call scripts by
path (`scaffold/new_service.py`, `platform/workflows/scripts/platform_deploy.py`). A
developer has to clone the platform repo to use them.

**Gap.** Every developer needs the platform repo checked out, skills drift with whatever
branch they have, and the platform team can't roll out a skill update to everyone.

**Proposal.**
1. **Package the tools the skills call**:
   - publish `platform-cli` (the deploy CLI plus the scaffolder) as a versioned Python
     package;
   - fetch the templates from their own template repos;
   - pull the chart schema from the chart registry (`helm show values` / the published
     `values.schema.json`).
   Skills then reference `platform-cli new-service …` rather than repo paths.
2. **Publish the developer skills to the shared AI vault** (the org's Claude Code plugin
   marketplace): `new-service`, `promote-service`, `decommission-service`, the future
   `migrate-service`, and the resource standards from section 7. Enable the vault for
   everyone through managed settings (org-wide `extraKnownMarketplaces` / enabled
   plugins), so every developer's Claude Code has them with no clone.
3. **Version them**: skills declare the CLI and chart versions they target. Vault releases
   follow chart releases, and the skills' worked examples stay tested in CI (as
   `tests/test_cookbook.py` does today).
4. **Keep platform-team skills** (`update-chart`, bootstrap and RGD authoring) in the
   platform repos, where only that team works.

**Done when** a developer with a fresh laptop and the org's managed Claude Code settings
can run `/new-service` to a deployed service without cloning any platform repo.

## 7. Per-resource standards for agents (AWS and Kubernetes)

**Today.**
- Agents know *what is possible* (the schema and the cookbook) and the platform contracts.
- They do not know *what good looks like* for each resource type.

**Gap.**
- The platform can't stop agents generating valid-but-poor shapes: a queue whose
  visibility timeout is shorter than processing time, a hot DynamoDB partition key, an
  unbounded `Scan`, a missing PDB, no graceful shutdown.
- Each agent re-invents the guidance.

**Proposal.** One standard per resource kind, in the vault (section 6), loaded on demand
by the skills (progressive disclosure: only the kinds a service uses).

| AWS | Kubernetes / app |
|---|---|
| SQS (visibility timeout vs. processing time, long polling, idempotent consumers, DLQ and redrive, FIFO only when ordering matters) | Probes (liveness never checks dependencies; readiness gates traffic; startup for slow boots) |
| DynamoDB (key design from access patterns, avoiding hot keys, Query not Scan, GSIs, TTL, item size, conditional writes) | Resources (requests from measured usage, memory limits, no CPU limits by default) |
| S3 (key layout, lifecycle and versioning, presigned URLs, never public) | Scaling (HPA vs KEDA choice, min replicas, PDB) |
| SNS (fan-out vs queue, filter policies, message size) | Graceful shutdown (SIGTERM handling, `terminationGracePeriodSeconds`, draining consumers) |
| RDS (IAM auth, connection pooling, migrations, read replicas) | Config and secrets (env vs mounted, External Secrets, never in values) |
| ALB/NLB (when each, health check paths, TLS) | Logging and metrics contract (sections 3 and 5) |

Each standard has the same shape:
- when to use it (and when not);
- required settings;
- recommended values;
- anti-patterns;
- the **values snippet** to declare it;
- **code snippets** per preset language (Python, Go, Java) for using it correctly.

As with the cookbook, CI validates the snippets: values snippets against the chart
schema, and code snippets compiled or run against LocalStack. The `new-service` skill
cites the relevant standard when it explains what it created, and reviewer agents use
the standards as their checklist on service PRs.

**Done when** each kind the chart supports has a tested standard in the vault, and
`/new-service` loads and applies the right ones for the resources a developer asks for.

## Suggested order

| # | Item | Why this position | Rough size |
|---|---|---|---|
| 1 | IAM guardrails (1) | Security floor; the boundary's `sqs:*` should go first | S–M |
| 2 | Peer review before prod (2) | Cheap (rulesets + one promote check), closes a governance gap | S |
| 3 | Mandatory autoscaling (4) | Schema change; better before many services adopt the chart | M |
| 4 | PagerDuty + alerting (3) | Needs the new-service input and a Terraform root; high value before broad rollout | M |
| 5 | Logging (5) | Builds on Alloy; mostly config plus preset changes | M |
| 6 | Per-resource standards (7) | Content-heavy; can start in parallel with 1–5 | M–L |
| 7 | Shared AI vault (6) | Needs `platform-cli` packaged first; then a mostly mechanical move | M |

Items 3, 4 and 5 change the chart contract, so ship them in one minor chart release with
a migration note. That release also fits naturally alongside the migration Phase 0 work
([migration.md](migration.md)).
