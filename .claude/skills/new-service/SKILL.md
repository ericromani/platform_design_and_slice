---
name: new-service
description: >-
  Walk a developer through creating (or updating) a microservice on the platform: ask what
  the service needs, scaffold the repo from the right language preset, and write a
  deploy/values-staging.yaml and values-prod.yaml that validate against the central
  microservice chart, so the first Argo CD sync creates every Kubernetes and AWS resource
  (SQS, SNS, S3, DynamoDB, RDS, ALB/NLB, IRSA role) without the developer learning the
  values format. Use when someone wants a new service, a new repo from a template, to add
  a queue/table/bucket/topic/database or a load balancer to a service, or to "set up my
  values file"; also for "what do I need to deploy X".
---

# New service (and update) — guided values

You are the developer's platform guide. The developer describes their service in plain
language; you translate that into a valid values file. They should never have to read
the chart schema. You must.

**Contract:** `platform/charts/microservice/values.schema.json` (authoritative) and
`references/values-cookbook.md` (worked snippets). Read the cookbook before writing values.

## Mode

- **New**: no service repo yet, so you scaffold, then write values.
- **Update**: a repo with `deploy/values-*.yaml` already exists (for example
  `examples/orders-service`). Read both files first and change only what the developer asks.
  An update journey is the same file edit plus a merge; the pipeline does the rest.

## 1. Interview (ask, don't assume)

Ask in at most two rounds, batching related questions (use the question tool when
available). Offer sensible defaults and say what they are.

Round 1, identity:
- service name (DNS label of 32 chars or fewer, e.g. `orders-service`), owning team, one-line purpose;
- language: `python` (FastAPI), `go` (net/http), or `java` (Spring Boot).

Round 2, what it touches (ask about each, in plain words):
- **Consumes messages?** From which queue, and is it FIFO? → `aws.sqs` `consume`
- **Sends messages / events?** To a queue (point-to-point) or a topic (fan-out)? → `aws.sqs` `publish` / `aws.sns` `publish`
- **Stores records?** Lookup by what key? Range queries by what? → `aws.dynamodb`
- **Stores files/blobs?** Read-only or read-write? Versioned? → `aws.s3`
- **Needs a relational DB?** Postgres or MySQL? → `aws.rds` (not available locally)
- **Receives HTTP traffic?** Only from inside the cluster (default), from the internal
  network (internal ALB/NLB), or from the internet (internet-facing, needs a cert)?
- **Load**: expected steady replicas, and should it autoscale on CPU?
- **Data retention on decommission**: keep (default for tables/buckets/DBs) or delete?
  Keeping means `deletionPolicy: retain` and, for tables and DBs, AWS
  `deletionProtection: true` (both default). Only for genuinely disposable data set
  `deletionPolicy: delete` and `deletionProtection: false` together.

If an answer implies something the platform cannot do (for example cross-account access,
a resource another service owns, or admin IAM), say so. Do not work around it with `env`
or by widening access; suggest the owning team expose it instead.

## 2. Map answers to values

| Developer says | Values |
|---|---|
| "reads jobs from a queue" | `aws.sqs: [{name: jobs, access: consume}]` |
| "puts work on a queue" | `aws.sqs: [{name: jobs, access: publish}]` |
| "both reads and writes that queue" | `access: consumepublish` |
| "strict ordering / exactly-once" | `fifo: true` (queue name gets `.fifo`) |
| "emits events others subscribe to" | `aws.sns: [{name: events, access: publish}]` |
| "stores orders by id" | `aws.dynamodb: [{name: orders, access: readwrite, partitionKey: {name: orderId, type: string}}]` |
| "…and queries them by date" | add `sortKey: {name: createdAt, type: string}` |
| "only reads that table" | `access: read` |
| "keeps uploaded files" | `aws.s3: [{name: uploads, access: readwrite}]` |
| "Postgres database" | `aws.rds: [{name: db, engine: postgres, access: connect}]` |
| "internal API for other teams" | `expose.loadBalancer: {enabled: true, type: alb, scheme: internal}` |
| "public HTTPS API" | `type: alb, scheme: internet-facing, certificateArn: …, host: …` |
| "TCP / gRPC passthrough" | `type: nlb` |
| "spiky load" | `autoscaling: {enabled: true, minReplicas: 2, maxReplicas: N}` |

Rules:
- Logical names (`name:`) are short (24 chars or fewer), lowercase and unique per type.
  The physical name becomes `<service>-<name>`.
- Key `type` is spelled `string | number | binary`, never `S/N/B`.
- Never set `global`, `image.tag` (keep `replaced-by-pipeline`), or env vars starting
  `AWS_`, `SQS_`, `SNS_`, `S3_`, `DYNAMODB_`, `RDS_` or `PLATFORM_` (platform-injected).
- Probes and `metrics.path` must be declared explicitly (the presets serve `/healthz`,
  `/readyz`, `/metrics`).
- Staging and prod normally differ only in `replicas`, `rollout.canaryWeights` /
  `pauseSeconds`, and sometimes autoscaling bounds. Keep the `aws:` block identical
  unless the developer has a reason.
- Load balancers are not available in local mode. Say so if the developer will test locally.

## 3. Scaffold (new mode only)

```bash
python scaffold/new_service.py --name <svc> --team <team> --language <lang> \
  --description "<purpose>" --dest <path> [--git]
```

Ask before adding `--create-github` (it publishes a repo to `<org>/<svc>`). Without it,
tell the developer how to create the repo themselves.

## 4. Write the values files

Edit `deploy/values-staging.yaml` and `deploy/values-prod.yaml` in the service repo,
following the cookbook. Keep the comment header the preset ships.

## 5. Validate (mandatory; never skip)

```bash
.venv/bin/python platform/workflows/scripts/platform_deploy.py validate --values <repo>/deploy/values-staging.yaml
.venv/bin/python platform/workflows/scripts/platform_deploy.py validate --values <repo>/deploy/values-prod.yaml
```

If validation fails, fix every listed path and re-run until both pass. Then render to show
the developer what the first sync will create (requires `make infra` for the globals file):

```bash
.venv/bin/python platform/workflows/scripts/platform_deploy.py render --env staging --tag preview \
  --values <repo>/deploy/values-staging.yaml | grep -E '^kind:|^  name:'
```

## 6. Tell the developer, briefly

- What will be created: each AWS resource, with its access level and env var name (for
  example `SQS_JOBS_QUEUE_NAME`).
- What their code must do: read those env vars, report work through the preset's
  recorder, keep `/readyz` honest.
- How it ships: open a PR (CI builds and tests, and checks the values); merging to `main`
  deploys to staging with a canary and metric analysis; the same image is promoted to
  prod only after staging passes. Locally: `make deploy-staging SERVICE_DIR=<repo>`.

## Pre-flight check (before you report done)

Re-read the rules in section 2 and confirm each of these:
- [ ] both values files validate (you ran the command and saw `valid`);
- [ ] no `global`, no real image tag, no reserved env-var prefixes;
- [ ] every resource the developer mentioned is declared, and nothing they did not mention;
- [ ] access levels are the narrowest that work (`read` before `readwrite`, `consume`
      before `consumepublish`);
- [ ] data stores' `deletionPolicy` and `deletionProtection` match what the developer chose
      (protection stays on unless the data is disposable);
- [ ] you asked before any outward-facing action (`--create-github`, pushing, opening a PR).
