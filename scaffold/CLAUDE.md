# scaffold — agent guide

`new_service.py` creates a service repo from a preset (standard library only):

```bash
python scaffold/new_service.py --name <svc> --team <team> --language python|go|java \
  --description "<one line>" --dest ../<svc> [--git] [--create-github] [--org example-org]
```

- Names must be DNS labels of 32 chars or fewer (they become Kubernetes and AWS names).
  The script refuses an existing `--dest`.
- `--create-github` publishes a repo (`gh repo create --private --push`). It is
  outward-facing: always confirm with the user first (the `new-service` skill does).
- After scaffolding, the `aws:` block in `deploy/values-*.yaml` is empty. Fill it with the
  `new-service` skill or by hand, then validate.
- Tests: `tests/test_scaffold.py` scaffolds every preset and validates its values.
