# templates — agent guide (platform team)

Language presets that `scaffold/new_service.py` copies into a new service repo:
`python-fastapi`, `go-http`, `java-springboot`. Placeholders (`__SERVICE_NAME__`,
`__TEAM__`, `__DESCRIPTION__`, `__IMAGE_REPOSITORY__`, `__GO_MODULE__`, `__JAVA_GROUP__`,
`__JAVA_PACKAGE__`, `__JAVA_PACKAGE_PATH__`) are replaced in contents and paths.

**The `CLAUDE.md` inside each preset ships to the service repo.** Write it for the service
developer, not for the platform team.

## Every preset must

- serve `/healthz`, `/readyz`, `/metrics` on port 8080 and emit the metrics contract
  (`http_requests_total`, `app_work_items_total{outcome}`, `app_work_duration_seconds`);
- run as uid 10001 with a read-only root filesystem (writes only to `/tmp`);
- ship passing unit tests (including a *contract* test of probes + metrics) and an
  integration test that runs against LocalStack when `LOCALSTACK_ENDPOINT` is set;
- ship `deploy/values-{staging,prod}.yaml` that validate against the chart, and the three
  thin workflows (`ci.yaml`, `deploy.yaml`, `decommission.yaml`) calling the central ones.

## Verifying a preset change

`make test` runs `tests/test_scaffold.py` (scaffold + values validation for every preset).
For code changes, also scaffold into `.tmp/` and run the preset's own checks:
- python: `ruff check . && ruff format --check . && pytest`
- go: `gofmt -l . && go vet ./... && go test -race ./... && staticcheck ./...`
- java: `./mvnw test` and `./mvnw verify -DskipUnitTests` (with `LOCALSTACK_ENDPOINT`)
Keep `go.sum` / the Maven wrapper in sync when changing dependencies; dependency bumps are
their own PR.
