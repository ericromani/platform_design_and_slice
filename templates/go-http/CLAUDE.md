# __SERVICE_NAME__ — agent guide

__DESCRIPTION__ Owned by **__TEAM__**. Go service on the platform; built, tested and
deployed by the platform's central pipelines, so you only write the service.

## Where to work

- Code: `internal/work/` (logic), `internal/server/` (HTTP), `cmd/server/` (wiring + readiness)
- Tests: `*_test.go` (table-driven), `test/integration/`. Fill in the TODOs as you build; keep the contract tests.
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

- Unit: `go vet ./... && go test -race ./...`
- Integration: `LOCALSTACK_ENDPOINT=http://localhost:4566 go test -tags integration ./...`
- CI runs the same plus the deploy-contract check; merging to `main` deploys to staging
  (canary + analysis) and then promotes the same image to prod.
