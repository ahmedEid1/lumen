# Single security group for the demo box. Default VPC's "default" SG
# allows all egress + all-internal ingress, but we don't want to mutate
# the default — create our own and attach it to the instance.

resource "aws_security_group" "lumen" {
  name        = "${var.project}-prod-sg"
  description = "Lumen demo box: SSH + HTTP + HTTPS ingress, all egress."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  ingress {
    description = "HTTP (Caddy ACME http-01 challenge + plain redirect to 443)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS (Caddy-terminated TLS to the app)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Everything outbound - package installs, Groq API, Lets Encrypt, etc."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
