#!/usr/bin/env bash
# Build the image, push it to ECR, and deploy the CloudFormation stack.
# Usage: VPC_ID=vpc-... SUBNETS=subnet-a,subnet-b [CERT_ARN=...] [ALERT_EMAIL=...] ./deploy/aws/deploy.sh
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
STACK="${STACK:-healthtrace}"
REPO="${REPO:-healthtrace}"
TAG="${TAG:-$(git rev-parse --short HEAD)}"
: "${VPC_ID:?set VPC_ID}"
: "${SUBNETS:?set SUBNETS (comma separated, two AZs)}"

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE="${REGISTRY}/${REPO}:${TAG}"

aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$REPO" --image-scanning-configuration scanOnPush=true --region "$REGION" >/dev/null
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

docker build --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"

aws cloudformation deploy \
  --region "$REGION" \
  --stack-name "$STACK" \
  --template-file deploy/aws/healthtrace.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    ImageUri="$IMAGE" \
    VpcId="$VPC_ID" \
    PublicSubnetIds="$SUBNETS" \
    CertificateArn="${CERT_ARN:-}" \
    AlertEmail="${ALERT_EMAIL:-}" \
    EnvironmentName="${ENVIRONMENT:-production}"

aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs" --output table
