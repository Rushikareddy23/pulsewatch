output "app_url" {
  value = "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "github_actions_variables" {
  description = "Add these as repository Variables in GitHub (Settings > Secrets and variables > Actions)"
  value = {
    AWS_REGION          = var.region
    AWS_DEPLOY_ROLE_ARN = aws_iam_role.deploy.arn
    ECR_REPOSITORY      = aws_ecr_repository.backend.name
    ECS_CLUSTER         = aws_ecs_cluster.main.name
    WEB_BUCKET          = aws_s3_bucket.web.bucket
    CLOUDFRONT_ID       = aws_cloudfront_distribution.web.id
  }
}
