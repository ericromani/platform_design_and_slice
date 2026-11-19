# tests — agent guide

Repo-level tests (`make test-python`, or `.venv/bin/python -m pytest`), no cluster needed:

- `test_iam_least_privilege.py` is the **static least-privilege proof** (LocalStack does not
  enforce IAM). For each RGD policy it checks:
  - exact action sets per access level;
  - the resource is only that RGD's own resource;
  - every action is inside the Terraform permissions boundary.
  A new access level or resource type must add its expected actions here.
- `test_platform_deploy.py` covers the deploy CLI's validation, merging and Application shape.
- `test_scaffold.py` checks that every preset scaffolds without leftover placeholders and
  that its values validate.

Chart template behaviour is tested with helm-unittest in
`platform/charts/microservice/tests/`. Service code is tested inside each service.
