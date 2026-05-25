# `infra/aws/` — Terraform stack for the Lumen demo box

One `terraform apply` brings up the Lumen production target on AWS:
an EC2 **t4g.small** (ARM Graviton2, 2 vCPU + 2 GB RAM) running
Canonical Ubuntu 24.04, a 30 GB gp3 root volume, a Security Group
with 22/80/443 ingress, and an Elastic IP. Total wall-clock on a new
AWS Free Plan account: **$0**.

## Prereqs

- **AWS CLI configured with a named profile.** The provider reads
  `~/.aws/credentials` profile `lumen` by default (override via
  `-var aws_profile=...`). Set it up with:

  ```bash
  aws configure --profile lumen
  ```

  The IAM user only needs `AmazonEC2FullAccess` + `IAMReadOnlyAccess`
  (the second is just so `aws sts get-caller-identity` works inside
  this directory).

- **Terraform ≥ 1.6.0.** Install via `winget install Hashicorp.Terraform`
  on Windows or [tfenv](https://github.com/tfutils/tfenv) on macOS/Linux.

## Use

```bash
cd infra/aws
terraform init
terraform plan
terraform apply -auto-approve

# Capture outputs
terraform output -raw public_ip          # the Elastic IP
terraform output -raw dns_nip_io         # <eip>.nip.io shortcut for ACME
terraform output -raw ssh_command        # copy-paste ssh string
```

After `apply`:

```bash
# Connect (the .pem was generated locally — see keys/)
$(terraform output -raw ssh_command)

# Run the bootstrap script (4 GB swap + Docker + hardened sshd + ufw + fail2ban)
sudo bash -c 'curl -fsSL https://raw.githubusercontent.com/ahmedEid1/E-Learning-Platform/master/scripts/aws-bootstrap.sh | bash'

# Or non-interactive (Terraform-friendly):
LUMEN_BOOTSTRAP_NONINTERACTIVE=1 \
  ADMIN_USER=lumen \
  APP_DOMAIN=$(terraform output -raw dns_nip_io) \
  ADMIN_EMAIL=you@example.com \
  sudo -E bash scripts/aws-bootstrap.sh
```

Full deploy runbook (rsync repo → `.env.production` → `docker compose
up` → smokes) is in [`../../docs/deployment/aws-vps.md`](../../docs/deployment/aws-vps.md).

## Tear down

```bash
terraform destroy
```

This removes the EC2 instance, EIP, security group, key pair, and
local key files. Nothing else costs money so this is the only cleanup
needed.

## What's intentionally not here

- **No remote state backend.** State lives in `terraform.tfstate` next
  to this README. For a portfolio demo this is fine; for a team or a
  production deploy you'd want an S3 backend with DynamoDB locking.
  Add `backend "s3" { ... }` to `versions.tf` to switch.
- **No EBS snapshot lifecycle policy.** Backups are handled inside the
  compose stack's `backup` profile (Postgres-dump + gzip to
  `./backups/`); you'd add `aws_dlm_lifecycle_policy` here if you
  wanted automated EBS-level snapshots.
- **No Route 53 zone.** The default uses `<eip>.nip.io` for the demo
  hostname so we don't need a domain. If you own a domain, add an A
  record manually at your registrar pointing at `aws_eip.lumen.public_ip`.

## File layout

| File | Purpose |
|---|---|
| `versions.tf`  | Terraform + provider version pins |
| `variables.tf` | Inputs (region, instance type, project name, SSH CIDR) |
| `main.tf`      | Provider config + data sources (default VPC, subnet, latest Ubuntu 24.04 arm64 AMI) |
| `network.tf`   | Security group |
| `compute.tf`   | TLS keypair + EC2 instance + Elastic IP |
| `outputs.tf`   | Public IP, SSH command, instance ID |
| `.gitignore`   | `.terraform/`, state, generated keys |
