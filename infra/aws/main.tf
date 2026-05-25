# Provider config + the default tags applied to every resource we create.
# default_tags lifts the per-resource `tags = { ... }` plumbing — handy
# when you scan Cost Explorer or the Resource Groups console.

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Repo      = "ahmedEid1/E-Learning-Platform"
    }
  }
}

# Default VPC — every AWS account ships with one per region, free, with
# internet gateway + public subnet in each AZ. Re-using it instead of
# creating a fresh VPC keeps the demo simple and avoids burning the
# 5-VPCs-per-region default limit.
data "aws_vpc" "default" {
  default = true
}

# Pick the first AZ's default public subnet. Default subnets all have
# auto-assign-public-ip enabled and a route to the IGW, so the instance
# gets a public IP out of the box (we attach an Elastic IP on top for a
# stable address that survives stop/start).
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

# Latest Canonical-published Ubuntu 24.04 LTS arm64 AMI. Looking it up
# means the .tf doesn't go stale when Canonical re-publishes — every
# `terraform plan` resolves to today's image.
data "aws_ami" "ubuntu_2404_arm64" {
  most_recent = true
  owners      = ["099720109477"] # Canonical's official AWS account ID

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
