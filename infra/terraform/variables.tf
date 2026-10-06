variable "project" {
  type    = string
  default = "pulsewatch"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "alert_email" {
  description = "Email that sends monitor alerts (verified in SES) and receives infrastructure alarms."
  type        = string
}

variable "github_repo" {
  description = "GitHub repo allowed to deploy, as owner/name (e.g. Rushikareddy23/pulsewatch)."
  type        = string
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro" # free-tier eligible for 12 months on new accounts
}

variable "api_desired_count" {
  type    = number
  default = 1
}

variable "worker_desired_count" {
  type    = number
  default = 1
}

variable "bootstrap_image_tag" {
  description = "Image tag for the first task definitions. Later deploys pin each release to its git SHA."
  type        = string
  default     = "bootstrap"
}
