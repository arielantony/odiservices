# Remotely managed tunnel: the origin has no open port, cloudflared dials out.
resource "cloudflare_zero_trust_tunnel_cloudflared" "portal" {
  account_id = var.account_id
  name       = "odiservices-portal"
  config_src = "cloudflare"
}

# Only the web container is reachable; everything else gets a 404.
resource "cloudflare_zero_trust_tunnel_cloudflared_config" "portal" {
  account_id = var.account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.portal.id
  config = {
    ingress = [
      { hostname = var.hostname, service = "http://127.0.0.1:8080" },
      { service = "http_status:404" },
    ]
  }
}

# Nothing but these addresses and domains allows.
resource "cloudflare_zero_trust_access_policy" "allow" {
  account_id       = var.account_id
  name             = "odiservices-portal allow"
  decision         = "allow"
  session_duration = var.session_duration
  include = concat(
    [for e in var.allowed_emails : { email = { email = e } }],
    [for d in var.allowed_email_domains : { email_domain = { domain = d } }],
  )
}

# The account has no One-time PIN provider by default (found in OPS-04 step 1).
resource "cloudflare_zero_trust_access_identity_provider" "pin" {
  account_id = var.account_id
  name       = "One-time PIN"
  type       = "onetimepin"
  config     = {}
}

resource "cloudflare_zero_trust_access_application" "portal" {
  account_id   = var.account_id
  name         = "odiservices-portal"
  domain       = var.hostname
  type         = "self_hosted"
  allowed_idps = [cloudflare_zero_trust_access_identity_provider.pin.id]

  auto_redirect_to_identity = true
  session_duration          = var.session_duration
  policies                  = [{ id = cloudflare_zero_trust_access_policy.allow.id, precedence = 1 }]
}

# The name never exists without Access in front of it.
resource "cloudflare_dns_record" "portal" {
  zone_id = var.zone_id
  name    = var.hostname
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.portal.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1

  depends_on = [
    cloudflare_zero_trust_access_application.portal,
    cloudflare_zero_trust_access_policy.allow,
  ]
}

data "cloudflare_zero_trust_tunnel_cloudflared_token" "portal" {
  account_id = var.account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.portal.id
}
