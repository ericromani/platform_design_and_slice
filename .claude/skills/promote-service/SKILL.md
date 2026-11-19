---
name: promote-service
description: >-
  Promote a service's image from staging to production on the platform, or explain why it
  cannot be promoted yet. Checks the staging verification record for the exact image tag
  (written only after a healthy canary with passing metric analysis), then runs the
  promotion with the same health gate and automatic rollback. Use for "ship to prod",
  "promote", "is my build ready for production", "why was promotion refused", or a stuck
  or failed prod deploy.
---

# Promote a service to prod

Prod accepts only image tags that passed staging. In CI this is the `prod` job of the
service's `deploy.yaml` (it runs `promote.yaml` after the staging job, and the
`production` GitHub environment may require a reviewer). Use this skill to check
readiness, run it locally, or diagnose a refusal.

## Steps

1. **Identify** the service (`service.name` in `deploy/values-prod.yaml`) and the tag: the
   short git SHA CI built. Locally, use the tag of the last staging deploy:
   `kubectl -n argocd get application <svc>-staging -o jsonpath='{.spec.source.helm.valuesObject.image.tag}'`.
2. **Check staging verification** (staging credentials):
   ```bash
   .venv/bin/python platform/workflows/scripts/platform_deploy.py check-verified \
     --tag <tag> --values <repo>/deploy/values-prod.yaml
   ```
   If it is missing, the tag never completed a healthy staging rollout. Do not try to
   bypass this: deploy to staging first (`make deploy-staging`) and read why it failed (the
   output names the failing analysis metric).
3. **Validate prod values**: `platform_deploy.py validate --values <repo>/deploy/values-prod.yaml`.
   Compare its `aws:` block with staging's and flag any difference to the developer,
   because prod would create resources staging never exercised.
4. **Confirm with the developer** that they want to deploy to production now. This changes a
   running environment.
5. **Promote**: locally `make promote TAG=<tag>`; in CI re-run the `prod` job, or push to
   `main`.
6. **Report** the outcome. On failure the tool has already rolled prod back to the last
   good release. Relay the failing metric (`work-failure-ratio`, `http-error-ratio`,
   `canary-up`) and point at the Grafana dashboard "Platform / Service health".

## Never

- Never call `deploy --env prod` directly or use `--i-am-the-promote-pipeline`; that flag
  exists only for `promote.yaml`.
- Never write to `/platform/promotions/*` by hand.
