# orders-service — agent guide

Consumes order events from SQS and records them in DynamoDB. Owned by **commerce**. Python service on the platform; built, tested and
deployed by the platform's central pipelines, so you only write the service.

## Where to work

- Code: `app/orders.py` (pure domain logic), `app/worker.py` (SQS → DynamoDB loop), `app/main.py` (HTTP + readiness), `app/config.py` (env contract)
- Tests: `tests/unit/`, `tests/integration/`. Fill in the TODOs as you build; keep the contract tests.
- Deploy intent: `deploy/values-staging.yaml`, `deploy/values-prod.yaml`.
- Do **not** edit `.github/workflows/`: they call `example-org/platform-workflows@v1`.

## Platform contract (deploys fail without it)

- Serve `/healthz` (liveness; never check dependencies), `/readyz` (readiness; 503 until
  your dependencies are reachable) and `/metrics` on port 8080.
- Count every unit of work as `app_work_items_total{outcome="success|failure|rejected"}`.
  A canary whose failure ratio exceeds `rollout.analysis.maxWorkFailureRatio` is rolled
  back automatically, so classify bad input as `rejected`, not `failure`.
- AWS resources are declared in `aws:` in the values files, never created by code. Each one
  arrives as env vars (`SQS_<NAME>_QUEUE_NAME`, `DYNAMODB_<NAME>_TABLE`,
  `SNS_<NAME>_TOPIC_ARN`, `S3_<NAME>_BUCKET`, `RDS_<NAME>_INSTANCE_ID`), and the pod's
  IRSA role can reach exactly those resources.

## Changing deploy settings or AWS resources

Use the platform's `/new-service` skill (update mode). It asks what you need and writes
valid values. Otherwise edit by hand against the chart schema
(`values.schema.json` in the platform chart) and validate:
`python platform/workflows/scripts/platform_deploy.py validate --values deploy/values-staging.yaml`.

## Checks before you push

- Unit: `pip install -r requirements-dev.txt && ruff check . && pytest tests/unit`
- Integration: `LOCALSTACK_ENDPOINT=http://localhost:4566 pytest -m integration`
- CI runs the same plus the deploy-contract check; merging to `main` deploys to staging
  (canary + analysis) and then promotes the same image to prod.

## This service (the platform's vertical slice)

- Declares one SQS queue (`orders`, access `consume`) and one DynamoDB table (`orders`,
  `readwrite`, partition key `orderId`). Its IRSA role can do nothing else.
- Outcomes: valid orders → `success` (row written, message deleted); malformed →
  `rejected` (deleted); processing errors → `failure` (left for retry).
- `deploy/faults/fail-all.yaml` is a values overlay (`FAIL_RATE=1`) used by
  `make break-and-rollback` to prove a bad release is rolled back automatically.
- Local loop: `make deploy-staging`, then `python local/orders_traffic.py send|verify|iam`.
