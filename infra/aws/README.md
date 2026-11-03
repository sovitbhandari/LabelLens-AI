# AWS deployment notes (not yet provisioned)

These files are **configuration sketches** prepared after local functionality was verified.
They do **not** mean AWS resources have been created.

## Intended services

| Component | Suggested AWS service |
|-----------|------------------------|
| API | ECS Fargate + Application Load Balancer |
| Web | S3 + CloudFront (static Vite build) or ECS |
| Database | RDS PostgreSQL 16 with `pgvector` extension |
| Secrets | Secrets Manager (`OPENAI_API_KEY`, `ADMIN_TOKEN`, DB URL) |
| MLflow | ECS service with EFS artifact store (optional) |
| CI deploy | GitHub Actions OIDC → ECR push → ECS update |

## Prerequisites before applying

1. Local Docker Compose stack healthy
2. CI green on `main`
3. Explicit approval to incur AWS cost
4. Account/region selected

## Files

- `ecs-task-api.json` — task definition sketch for the API container
- `cloudformation-skeleton.yaml` — high-level VPC/RDS/ECS skeleton (not applied)

Do not run `aws cloudformation deploy` without explicit permission.
