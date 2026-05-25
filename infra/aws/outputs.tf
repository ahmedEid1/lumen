# Outputs the operator (or a follow-up shell loop) needs to actually
# talk to the box after apply.

output "instance_id" {
  description = "EC2 instance ID — paste into 'aws ec2 describe-instances --instance-ids' for troubleshooting."
  value       = aws_instance.lumen.id
}

output "public_ip" {
  description = "Stable Elastic IP. Survives instance stop/start; point DNS here."
  value       = aws_eip.lumen.public_ip
}

output "dns_nip_io" {
  description = "Free wildcard-DNS shortcut to the EIP. Useful for ACME http-01 if you don't own a domain."
  value       = "${aws_eip.lumen.public_ip}.nip.io"
}

output "ssh_command" {
  description = "Copy-pasteable SSH command using the Terraform-managed keypair."
  value       = "ssh -i ${var.ssh_key_dir}/${var.project}-prod.pem ubuntu@${aws_eip.lumen.public_ip}"
}

output "ssh_key_path" {
  description = "Local path to the private key file (chmod 0600). Pass via -i to scp / rsync."
  value       = "${var.ssh_key_dir}/${var.project}-prod.pem"
}

output "security_group_id" {
  description = "Attached SG ID — useful for follow-up `aws ec2 authorize-security-group-ingress` calls."
  value       = aws_security_group.lumen.id
}
