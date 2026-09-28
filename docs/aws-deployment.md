# AWS deployment

## Architecture

```
Route 53 (optional) -> ALB (HTTPS, ACM cert, WebSocket idle timeout 300 s)
                        -> ECS Fargate service, 1 task
                             app container (API + /ws + UI), port 8000
                             generator container (demo only), shared data volume
                        task role -> CloudWatch Logs (/healthtrace/<env>/alerts)
                                  -> SNS topic (HIGH and CRITICAL pages)
                        container logs -> CloudWatch Logs (/healthtrace/<env>/app)
                        OPERATOR_TOKEN <- Secrets Manager
Image: ECR
```

Why this shape:

- **Containers, not static hosting**: the backend holds live pipeline state
  and serves a WebSocket, so the UI is served by the same container.
- **One task**: detection state (windows, baselines, incident engine) lives
  in one process. Deployments replace the task (min 0 / max 100 percent) so
  two pipelines never page for the same anomaly. Scale up the task size, not
  the count.
- **No AWS keys**: the task role grants only `logs:*Put*/Create*` on the alert
  log group and `sns:Publish` on the topic.
- **Sign-in**: put an ALB `authenticate-cognito` action in front of the
  forward action for user login; the operator token protects write actions.

## Deploy

Prerequisites: AWS CLI v2, Docker, a VPC with two public subnets, optionally
an ACM certificate.

```bash
VPC_ID=vpc-xxxx SUBNETS=subnet-a,subnet-b CERT_ARN=arn:aws:acm:... ALERT_EMAIL=oncall@example.com \
  ./deploy/aws/deploy.sh
```

The script creates the ECR repository if needed, builds and pushes the image
(tagged with the git commit), deploys `deploy/aws/healthtrace.yaml`, and
prints the URL, SNS topic and the operator-token secret.

## Real logs instead of the generator

Set `RunGenerator=false` and ship application logs into the task's
`/app/data/logs/app.log` and `audit.log` (for example with a FireLens or
Fluent Bit sidecar writing JSON lines in the format of SPEC.md section 5).

## Limits

- The data volume is task storage: a replaced task relearns baselines from
  the log files it is given. Mount EFS at `/app/data` if baselines must survive
  replacement; expect slower writes, since SQLite on NFS is slower than local disk.
- Not verified against a live AWS account from this repository; the template
  passes `cfn-lint`.
