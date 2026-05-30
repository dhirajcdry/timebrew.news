#!/usr/bin/env bash
# Build the SPA and publish it to S3 + invalidate CloudFront.
# Bucket name and distribution id are read from the CloudFormation stack outputs
# so there is nothing hardcoded to keep in sync.
set -euo pipefail

PROFILE="${AWS_PROFILE:-dhiraj-aws-acct}"
STACK="timebrew-frontend-prod"

# 1. Build the frontend
npm run build

# 2. Resolve infra from stack outputs
BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK" --profile "$PROFILE" \
  --query "Stacks[0].Outputs[?OutputKey=='WebsiteBucketName'].OutputValue" --output text)
DIST=$(aws cloudformation describe-stacks --stack-name "$STACK" --profile "$PROFILE" \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDistributionId'].OutputValue" --output text)

echo "Deploying to bucket=$BUCKET distribution=$DIST"

# 3. Sync to S3
aws s3 sync ./dist "s3://$BUCKET" --delete --profile "$PROFILE"

# 4. Invalidate CloudFront cache
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/*" --profile "$PROFILE"
