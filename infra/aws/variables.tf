# Inputs the operator can override via -var, terraform.tfvars, or env vars.
# Defaults are chosen so `terraform apply` with no overrides produces a
# working Lumen prod box on the AWS Free Plan from the cheapest path.

variable "aws_region" {
  description = "AWS region. eu-central-1 (Frankfurt) is the default — closest free-tier-friendly region to the project's home."
  type        = string
  default     = "eu-central-1"
}

variable "aws_profile" {
  description = "Local ~/.aws/credentials profile to read. Use a named profile so the user's existing default/env-var setup isn't disturbed."
  type        = string
  default     = "lumen"
}

variable "project" {
  description = "Tag value applied to every billable resource — easy filtering in Cost Explorer."
  type        = string
  default     = "lumen"
}

variable "instance_type" {
  description = "EC2 instance type. t4g.small is the only type covered by AWS's free-trial promo through 2026-12-31."
  type        = string
  default     = "t4g.small"
}

variable "root_volume_gb" {
  description = "Root EBS gp3 volume size in GB. 30 GB is the free-tier ceiling on new accounts; bumping above 30 will start billing $0.08/GB-month."
  type        = number
  default     = 30
}

variable "allowed_ssh_cidr" {
  description = "CIDR block allowed to reach :22. 0.0.0.0/0 is fine for a demo (fail2ban + key-only auth handles abuse); narrow to your own /32 for a tighter posture."
  type        = string
  default     = "0.0.0.0/0"
}

variable "ssh_key_dir" {
  description = "Local directory where the generated SSH private + public keys are written. Default is alongside this Terraform module so they're easy to find."
  type        = string
  default     = "./keys"
}
