output "portal_url" {
  value = "https://${var.hostname}"
}

# For BE-23: <team>.cloudflareaccess.com. The team name is in the dashboard
# (Zero Trust > Settings > Custom Pages); it is not a resource here.
output "access_aud" {
  description = "AUD tag of the Access application, for verifying the JWT (BE-23)."
  value       = cloudflare_zero_trust_access_application.portal.aud
}

# The owner reads it once: tofu output -raw tunnel_token
output "tunnel_token" {
  value     = data.cloudflare_zero_trust_tunnel_cloudflared_token.portal.token
  sensitive = true
}
