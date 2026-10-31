output "public_ip" {
  description = "The instance's static address."
  value       = aws_lightsail_static_ip.portal.ip_address
}

output "ssh_command" {
  description = "How to reach the instance and tunnel to the portal."
  value       = "ssh -L 8080:127.0.0.1:8080 deploy@${aws_lightsail_static_ip.portal.ip_address}"
}
