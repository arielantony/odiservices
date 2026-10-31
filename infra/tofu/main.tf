resource "aws_lightsail_key_pair" "deploy" {
  name       = "odiservices-deploy"
  public_key = var.ssh_public_key
}

resource "aws_lightsail_instance" "portal" {
  name              = "odiservices-portal"
  availability_zone = var.availability_zone
  blueprint_id      = var.blueprint_id
  bundle_id         = var.bundle_id
  key_pair_name     = aws_lightsail_key_pair.deploy.name

  # No secret in user_data: it is stored in the state in plain text.
  user_data = templatefile("${path.module}/cloud-init.yaml", {
    ssh_public_key = trimspace(var.ssh_public_key)
  })
}

resource "aws_lightsail_static_ip" "portal" {
  name = "odiservices-portal"
}

resource "aws_lightsail_static_ip_attachment" "portal" {
  static_ip_name = aws_lightsail_static_ip.portal.name
  instance_name  = aws_lightsail_instance.portal.name
}

# Only SSH. The portal is reached through an SSH tunnel until OPS-04.
resource "aws_lightsail_instance_public_ports" "portal" {
  instance_name = aws_lightsail_instance.portal.name

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = var.ssh_allowed_cidrs
  }
}
