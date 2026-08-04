# Kureha — AWS Terraform (design.md §20, ADR-20)

IaC for the production deployment topology described in
`openspec/changes/kureha-mvp/design.md` §20: VPC/ALB/WAF/ECS Fargate/RDS
Single-AZ/NAT/Secrets Manager/IAM (task 16.1), EventBridge Scheduler + ECS
scheduled tasks (task 16.2), CloudWatch alarms + SNS (task 16.3), S3 +
CloudFront frontend tier (task 16.4).

**Tool decision:** Terraform (chosen over CDK/CloudFormation per
`tasks.md` task 16.1 — decided during this task, see the tasks.md closure
note for that ADR).

## Structure

```
infra/terraform/
  modules/
    network/            VPC, subnets, NAT, security groups
    secrets/             Secrets Manager: KEK, Google OAuth, Supabase,
                          Anthropic API key, internal signing secrets
    rds/                 RDS Postgres Single-AZ + its own credential secrets
    alb-waf/             ALB, target group, listeners, WAFv2 web ACL
    ecs/                 Cluster, IAM roles, API service task def + service,
                          bootstrap/migrate one-off task defs, verify/retry
                          scheduled task defs
    scheduler-alarms/    EventBridge Scheduler schedules, CloudWatch alarms,
                          SNS topic
    frontend-cdn/        S3 bucket + CloudFront distribution for the SPA
  envs/
    prod/                Root composition wiring all modules together
```

`infra/localstack/` and `infra/postgres/init/` (local dev, pre-existing)
are untouched by this tree — see design.md §22 for why local dev does NOT
use Terraform/real AWS resources at all (LocalStack Community covers
Secrets Manager/S3/SNS/CloudWatch; RDS/ALB/WAF/ECS/NAT/CloudFront have no
local equivalent and are not needed for `docker-compose.yml`'s `uvicorn`
dev server).

## Prerequisites (all out-of-band, not automated by this Terraform)

1. An AWS account + credentials with permission to create every resource
   type referenced below.
2. An S3 bucket + DynamoDB table for remote state (`envs/prod/backend.tf`
   is commented out until these exist — **do not `terraform apply` against
   local state for anything beyond a `plan`/`validate` dry run**; see that
   file's own comment for why: `modules/rds`/`modules/secrets` compose
   plaintext credentials into state).
3. An ACM certificate for the ALB's HTTPS listener, issued/validated in
   the deployment region.
4. (Optional) A second ACM certificate in **us-east-1** if using a custom
   CloudFront domain (`frontend_domain_aliases`) — CloudFront's own hard
   region requirement, independent of the ALB's region.
5. A backend container image already pushed to ECR (`backend/Dockerfile`,
   production target — not `Dockerfile.dev`).

## Apply order (informational — Terraform's own dependency graph already
enforces this; listed for a human reading the plan output)

1. `module.network` — VPC/subnets/SGs/NAT.
2. `module.secrets` / `module.rds` — secret containers + RDS instance
   (parallel, no dependency between them).
3. `module.alb_waf` — ALB/WAF (needs network only).
4. `module.ecs` — cluster, IAM roles, task definitions, the long-running
   API service (needs network + alb_waf's target group + rds/secrets'
   secret ARNs).
5. **Manual step, not run by `terraform apply`:** `aws ecs run-task
   --cluster <ecs_cluster_name output> --task-definition
   <bootstrap_db_task_definition_arn output> --launch-type FARGATE
   --network-configuration "awsvpcConfiguration={subnets=[...private
   subnets...],securityGroups=[...ecs sg...],assignPublicIp=DISABLED}"
   --wait tasks-stopped` — creates the `pgcrypto`/`btree_gist` extensions
   and the `app_runtime` role (tasks.md task 16.1's own explicit
   requirement: this MUST run before the first `alembic upgrade head`).
   Deliberately a manual/CI-pipeline step, not a Terraform-triggered
   `null_resource`, because Terraform itself typically runs OUTSIDE the
   VPC and cannot reach RDS directly (`Database not publicly reachable`,
   design.md §20) — matches the same constraint the ECS-task-based
   bootstrap design already exists to satisfy.
6. **Manual step:** same `aws ecs run-task` pattern against
   `migrate_task_definition_arn`, run on every deploy after step 5 has run
   at least once.
7. `module.scheduler_alarms` — EventBridge Scheduler + CloudWatch alarms +
   SNS (needs ecs's cluster/task-definition ARNs).
8. `module.frontend_cdn` — S3 + CloudFront (independent of the backend
   tier, can apply any time; the SPA's own static-export build/upload is a
   separate CI/CD step: `cd frontend && npm run build && aws s3 sync out/
   s3://<spa_bucket_name output>/ --delete`, followed by a CloudFront
   invalidation).

## What this Terraform deliberately does NOT do

- **Does not run `terraform apply`.** This task authors IaC for a future
  deployment; no real AWS resources were provisioned in this session (see
  tasks.md 16.1-16.4's own closure notes for exactly what validation WAS
  run: `terraform fmt -check` + `terraform validate` only).
- **Does not fabricate the two backend job entrypoints** `modules/ecs`'s
  `verify_audit_chain_task_definition`/`retry_calendar_sync_task_definition`
  invoke (`python -m app.jobs.verify_audit_chain` /
  `python -m app.jobs.retry_calendar_sync`) — neither exists in
  `backend/app/` today (confirmed by grep, see `modules/ecs/variables.tf`'s
  own comment). The calendar retry job has a real, tested use case
  (`RetryPendingCalendarSyncs`, tasks.md 9.5) but no CLI wrapper or
  per-tenant loop; the audit hash-chain verify job (design.md §4.3) has NO
  use-case-level implementation at all. This is a genuine backend-scope
  gap discovered while authoring this infra, flagged rather than invented
  — see tasks.md 16.2's closure note.
- **Does not add a dedicated `GET /health` endpoint** to the backend —
  `modules/alb-waf`'s health check uses `/openapi.json` as an interim
  target (flagged in that module's own variable description).
- **Does not create a real KEK/Google OAuth client/Supabase credential
  value.** `modules/secrets` creates the secret CONTAINERS with an
  obviously-fake placeholder (`CHANGE_ME_OUT_OF_BAND`); an operator
  populates the real value via `aws secretsmanager put-secret-value`
  after `apply`, never through Terraform config/state.

## Validation performed this task (see tasks.md 16.1 closure note for the
full statement)

- `terraform fmt -check -recursive` across `infra/terraform/`.
- `terraform init` + `terraform validate` per root config (`envs/prod`).
- **`terraform plan` was deliberately NOT run.** Real (temporary/STS) AWS
  credentials were present in this session's environment — running `plan`
  risks making live read-only AWS API calls (or worse) against a real
  account, which the task's own instructions explicitly forbid
  ("Do NOT provision real AWS resources or run `terraform apply` against a
  real account"). `validate` + `fmt` need no AWS credentials at all (only
  the already-downloaded provider schema), which is why they were judged
  safe to run and `plan` was not.
- No `checkov`/`tflint`/`terraform-compliance` available in this
  environment (checked, not assumed) — not installed, per the task's own
  instruction to state clearly what could not be validated rather than
  silently skip it.
