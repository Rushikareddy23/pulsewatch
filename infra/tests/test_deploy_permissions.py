"""Every AWS CLI call in the deploy workflow must be allowed by the deploy role in Terraform.
(Catches the classic "pipeline works locally, AccessDenied in CI" mistake.)"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/deploy.yml").read_text()
POLICY = (ROOT / "infra/terraform/github_oidc.tf").read_text()

# High-level CLI commands that map to several API actions.
SPECIAL = {
    ("ecs", "wait"): ["ecs:DescribeServices"],
    ("s3", "sync"): ["s3:ListBucket", "s3:PutObject", "s3:DeleteObject"],
    ("s3", "cp"): ["s3:PutObject"],
}


def required_actions() -> set[str]:
    actions = set()
    for svc, op in re.findall(r"\baws (\w+) ([a-z][a-z-]+)", WORKFLOW):
        if (svc, op) in SPECIAL:
            actions.update(SPECIAL[(svc, op)])
        else:
            actions.add(f"{svc}:" + "".join(w.capitalize() for w in op.split("-")))
    if "amazon-ecr-login" in WORKFLOW:
        actions.add("ecr:GetAuthorizationToken")
    if "docker push" in WORKFLOW:
        actions.update(["ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload",
                        "ecr:PutImage", "ecr:BatchCheckLayerAvailability"])
    if "register-task-definition" in WORKFLOW:
        actions.add("iam:PassRole")
    return actions


def test_workflow_uses_expected_commands():
    acts = required_actions()
    assert {"ecr:DescribeImages", "ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition",
            "ecs:UpdateService", "cloudfront:CreateInvalidation"} <= acts


def test_deploy_role_allows_every_action_the_workflow_uses():
    missing = sorted(a for a in required_actions() if f'"{a}"' not in POLICY)
    assert not missing, f"deploy role is missing: {missing}"


def test_passrole_is_scoped_to_ecs_task_roles():
    block = POLICY[POLICY.index("iam:PassRole"):][:400]
    assert "aws_iam_role.execution.arn" in block and "aws_iam_role.task.arn" in block
    assert '"iam:PassedToService" = "ecs-tasks.amazonaws.com"' in block


def test_every_container_gets_the_new_image():
    assert ".containerDefinitions |= map(.image = $img)" in WORKFLOW
