# Developer platform — local entry points. `make help` lists targets.
# Every target sources local/env.sh: repo-local tools, isolated kubeconfig/Helm/Docker config.
SHELL := /bin/bash
.SHELLFLAGS := -eo pipefail -c
.DEFAULT_GOAL := help

ENV          := source local/env.sh &&
PY           := .venv/bin/python
DEPLOY       := $(PY) platform/workflows/scripts/platform_deploy.py
CHART        := platform/charts/microservice
SERVICE_DIR  ?= examples/orders-service
SERVICE      := $(shell awk '/^  name:/ {print $$2; exit}' $(SERVICE_DIR)/deploy/values-staging.yaml)
TAG          ?= $(shell git rev-parse --short HEAD)
IMAGE        := localhost:5001/$(SERVICE):$(TAG)

.PHONY: help
help: ## Show targets
	@awk 'BEGIN{FS=":.*## "} /^[a-zA-Z_-]+:.*## /{printf "  \033[36m%-22s\033[0m %s\n",$$1,$$2}' $(MAKEFILE_LIST)

# ---- setup ---------------------------------------------------------------------------
.PHONY: tools
tools: ## Install pinned CLIs into .tools/ and the Python venv (.venv)
	./local/install-tools.sh

# ---- static checks (no cluster) -----------------------------------------------------
.PHONY: test test-python test-chart test-terraform test-workflows test-example
test: test-python test-chart test-terraform test-workflows test-example ## All static checks

test-python: ## Repo tests (IAM proof, deploy CLI, scaffold, cookbook) + lint
	$(PY) -m ruff check . && $(PY) -m ruff format --check .
	$(PY) -m pytest

test-chart: ## helm lint + helm-unittest + render/kubeconform of every values file
	$(ENV) helm lint $(CHART) -f $(CHART)/ci/full-values.yaml
	$(ENV) helm unittest $(CHART)
	$(ENV) helm template t $(CHART) -f $(CHART)/ci/full-values.yaml | kubeconform -strict -summary -ignore-missing-schemas
	@# Preset values hold placeholders; tests/test_scaffold.py validates them after rendering.
	$(ENV) for f in examples/*/deploy/values-*.yaml; do $(DEPLOY) validate --values $$f || exit 1; done

test-terraform: ## terraform fmt + validate for every root
	terraform fmt -recursive -check infra/terraform
	for r in infra/terraform/envs/*; do \
	  terraform -chdir=$$r init -backend=false -input=false >/dev/null && terraform -chdir=$$r validate; done

test-workflows: ## actionlint the central workflows and every preset's callers
	$(ENV) actionlint platform/workflows/.github/workflows/*.yaml templates/*/.github/workflows/*.yaml \
	  examples/*/.github/workflows/*.yaml .github/workflows/*.yaml

test-example: ## orders-service lint + unit tests (+ integration when LocalStack is up)
	cd $(SERVICE_DIR) && { [ -d .venv ] || (python3 -m venv .venv && .venv/bin/pip install -q -r requirements-dev.txt); } \
	  && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q tests/unit
	@if curl -fsS http://localhost:4566/_localstack/health >/dev/null 2>&1; then \
	  cd $(SERVICE_DIR) && LOCALSTACK_ENDPOINT=http://localhost:4566 .venv/bin/pytest -q -m integration; \
	else echo "LocalStack not running: skipping integration tests"; fi

# ---- local cloud --------------------------------------------------------------------
.PHONY: up cluster bootstrap infra publish-chart down
up: cluster infra bootstrap publish-chart ## Local cloud + Terraform prerequisite + platform add-ons

cluster: ## kind (EKS) + LocalStack (AWS) + registry (ECR)
	$(ENV) ./local/up.sh

infra: ## Apply the Terraform prerequisite to LocalStack (both accounts)
	terraform -chdir=infra/terraform/envs/local init -input=false >/dev/null
	terraform -chdir=infra/terraform/envs/local apply -auto-approve -input=false

bootstrap: ## kro + RGDs, ACK (per env), Prometheus/Grafana/Alloy, Argo Rollouts, Argo CD
	$(ENV) ./platform/bootstrap/install.sh all

publish-chart: ## Package and push the chart to the local OCI registry
	$(ENV) ALLOW_REPUBLISH=1 ./platform/workflows/scripts/publish_chart.sh oci://localhost:5001/charts --plain-http

down: ## Delete the cluster and containers
	$(ENV) ./local/down.sh

# ---- journeys -----------------------------------------------------------------------
.PHONY: build deploy-staging verify update break-and-rollback promote iam decommission clean-retained demo
build: ## Build + push the service image (tag = short git SHA)
	$(ENV) podman build -q -t $(IMAGE) $(SERVICE_DIR) && podman push -q --tls-verify=false $(IMAGE)

deploy-staging: build ## Journey 1/2: deploy to staging (canary, analysis, auto-rollback)
	$(ENV) $(DEPLOY) deploy --env staging --tag $(TAG) --values $(SERVICE_DIR)/deploy/values-staging.yaml

verify: ## Send orders through SQS and check they land in DynamoDB (orders-service)
	$(ENV) $(PY) local/orders_traffic.py send --env $${ENV_NAME:-staging} --count 20 --rate 10
	$(ENV) $(PY) local/orders_traffic.py verify --env $${ENV_NAME:-staging} --expect 20

update: ## Journey 2: redeploy under live traffic (watch the canary + analysis)
	$(ENV) ($(PY) local/orders_traffic.py send --env staging --rate 3 --duration 180 --count 0 >/dev/null 2>&1 &) ; \
	  $(DEPLOY) deploy --env staging --tag $(TAG) --values $(SERVICE_DIR)/deploy/values-staging.yaml

break-and-rollback: ## Deploy a release that fails every order; expect abort + rollback (exit 1 is success here)
	$(ENV) ($(PY) local/orders_traffic.py send --env staging --rate 3 --duration 240 --count 0 >/dev/null 2>&1 &) ; \
	  if $(DEPLOY) deploy --env staging --tag $(TAG) --values $(SERVICE_DIR)/deploy/values-staging.yaml \
	       --values $(SERVICE_DIR)/deploy/faults/fail-all.yaml; then \
	    echo "UNEXPECTED: faulty release was not rejected"; exit 1; \
	  else echo "OK: faulty release rejected and rolled back"; fi

promote: ## Promote TAG to prod (refused unless staging verified it)
	$(ENV) $(DEPLOY) promote --tag $(TAG) --values $(SERVICE_DIR)/deploy/values-prod.yaml

iam: ## Print the service role's live trust + policies (ENV_NAME=staging|prod)
	$(ENV) $(PY) local/orders_traffic.py iam --env $${ENV_NAME:-staging}

decommission: ## Journey 3: remove the service from staging, then prod (data retained)
	$(ENV) $(DEPLOY) decommission --service $(SERVICE) --env staging
	$(ENV) $(DEPLOY) decommission --service $(SERVICE) --env prod

clean-retained: ## LocalStack only: drop tables retained by a previous decommission (makes demo re-runnable)
	$(ENV) $(PY) local/orders_traffic.py clean-retained

demo: clean-retained deploy-staging verify update break-and-rollback promote ## All journeys end to end, then decommission
	ENV_NAME=prod $(MAKE) verify iam
	$(MAKE) decommission
