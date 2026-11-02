terraform {
  required_version = ">= 1.10.0"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "= 5.28.1"
    }
  }
}

# The API token comes from CLOUDFLARE_API_TOKEN in the operator's environment
# (~/.config/odiservices/cloudflare.env). Nothing in this repository holds it.
provider "cloudflare" {}
