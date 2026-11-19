# Values cookbook

Snippets that validate against `platform/charts/microservice/values.schema.json`. Combine
them under one `aws:` key. Every snippet assumes the preset's header (service, image,
probes, metrics) is present.

## Minimal (no AWS resources)

```yaml
service: {name: hello-api, team: web}
image: {repository: localhost:5001/hello-api, tag: replaced-by-pipeline}
probes:
  liveness: {path: /healthz}
  readiness: {path: /readyz}
metrics: {path: /metrics}
aws: {}
```

No IAM role is created; the ServiceAccount carries no IRSA annotation.

## Queue consumer → table writer (the orders-service slice)

```yaml
aws:
  sqs:
    - name: orders
      access: consume              # Receive/Delete/ChangeVisibility/GetQueueAttributes/GetQueueUrl
      visibilityTimeoutSeconds: 30 # > your worst-case processing time
  dynamodb:
    - name: orders
      access: readwrite
      partitionKey: {name: orderId, type: string}
      deletionPolicy: retain       # default for tables
```

Env: `SQS_ORDERS_QUEUE_NAME=<svc>-orders`, `DYNAMODB_ORDERS_TABLE=<svc>-orders`.

## Producer with fan-out

```yaml
aws:
  sns:
    - {name: order-events, access: publish}          # SNS_ORDER_EVENTS_TOPIC_ARN
  sqs:
    - {name: retries, access: consumepublish, fifo: true}   # queue name <svc>-retries.fifo
```

## Files

```yaml
aws:
  s3:
    - name: invoices
      access: readwrite            # or read
      versioning: true
      deletionPolicy: retain       # S3_INVOICES_BUCKET=<svc>-invoices-<account>
```

Bucket names include the account ID and must stay at 63 chars or fewer: keep `service.name`
plus `name` under about 48 chars.

## Relational database (AWS only; not in the local slice)

```yaml
aws:
  rds:
    - name: ledger
      engine: postgres             # or mysql
      engineVersion: "16.4"
      instanceClass: db.t4g.micro
      allocatedStorageGB: 20
      access: connect              # IAM DB auth as user <service_name_with_underscores>
```

Env: `RDS_LEDGER_INSTANCE_ID`. The master password stays in Secrets Manager (RDS-managed).
Prod gets Multi-AZ, deletion protection and 14-day backups automatically.

## Exposure

```yaml
expose:
  service: {port: 80}              # cluster-internal Service (always)
  loadBalancer:
    enabled: true
    type: alb                      # alb (HTTP, host/path routing) | nlb (TCP/TLS)
    scheme: internal               # internal | internet-facing
    host: orders.internal.example.com
    certificateArn: ""             # set for HTTPS (required for internet-facing)
```

## Scale and rollout

```yaml
replicas: 3                        # ignored when autoscaling.enabled
autoscaling: {enabled: true, minReplicas: 3, maxReplicas: 10, targetCPUUtilizationPercentage: 70}
resources:
  requests: {cpu: 250m, memory: 256Mi}
  limits: {memory: 512Mi}
rollout:
  canaryWeights: [25, 50]          # each step: setWeight -> pause -> analysis
  pauseSeconds: 30
  analysis:
    maxWorkFailureRatio: 0.02      # stricter than the 0.05 default
    maxHttpErrorRatio: 0.01
```

## Typical staging vs prod differences

| Key | staging | prod |
|---|---|---|
| `replicas` | 2 | 3+ |
| `rollout.canaryWeights` | `[50]` | `[34, 67]` |
| `rollout.pauseSeconds` | 20 | 30+ |
| `aws` | identical | identical |

## Validation errors you will see (and the fix)

| Error | Fix |
|---|---|
| `global: is injected by the platform pipeline` | delete the `global:` block |
| `probes.readiness.path: required` | declare `probes.readiness.path: /readyz` |
| `aws.sqs.0.access: 'read' is not one of …` | queues use `consume` / `publish` / `consumepublish` |
| `aws.dynamodb.0.partitionKey.type: True is not one of …` | you wrote `type: N`; use `type: number` |
| `env: 'AWS_REGION' should not be valid …` | platform-injected; remove it |
| `Additional properties are not allowed ('x')` | a typo or an unsupported field; check the schema |
