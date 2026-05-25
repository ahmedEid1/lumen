# Terraform + provider version pins. The 5.x AWS provider is the long-lived
# pre-6 line; pinning to ~> 5.70 lets patch releases through and blocks a
# breaking-change 6.0 bump without a deliberate edit here.
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}
