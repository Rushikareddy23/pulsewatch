# GitHub Actions deploys with short-lived credentials via OIDC: no AWS keys stored in GitHub.
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${var.project}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

resource "aws_iam_role_policy" "deploy" {
  role = aws_iam_role.deploy.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Sid = "EcrLogin", Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Sid = "EcrPushAndCheck", Effect = "Allow", Resource = aws_ecr_repository.backend.arn, Action = [
      "ecr:DescribeImages", "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload",
    "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage"] },
    # Describe/Register don't support resource-level permissions, so "*" is required here.
    { Sid = "TaskDefinitions", Effect = "Allow",
    Action = ["ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition"], Resource = "*" },
    { Sid = "RollOutServices", Effect = "Allow", Action = ["ecs:UpdateService", "ecs:DescribeServices"],
    Resource = [aws_ecs_service.api.id, aws_ecs_service.worker.id] },
    # Registering a task definition hands these roles to ECS; scope PassRole to exactly them.
    { Sid      = "PassTaskRoles", Effect = "Allow", Action = ["iam:PassRole"],
      Resource = [aws_iam_role.execution.arn, aws_iam_role.task.arn],
    Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } } },
    { Sid = "Frontend", Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.web.arn },
    { Sid = "FrontendObjects", Effect = "Allow", Action = ["s3:PutObject", "s3:DeleteObject"],
    Resource = "${aws_s3_bucket.web.arn}/*" },
    { Sid = "CacheInvalidation", Effect = "Allow", Action = ["cloudfront:CreateInvalidation"],
    Resource = aws_cloudfront_distribution.web.arn },
  ] })
}
