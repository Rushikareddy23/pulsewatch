terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.60" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # Optional: store state in S3 so CI and your laptop share it.
  # backend "s3" { bucket = "<your-state-bucket>" key = "pulsewatch/terraform.tfstate" region = "us-east-1" }
}

provider "aws" {
  region = var.region
  default_tags { tags = { Project = var.project, ManagedBy = "terraform" } }
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" { state = "available" }
