variable "account_id" {
  description = "Cloudflare account id. No default, so it never reaches the repository."
  type        = string
}

variable "zone_id" {
  description = "Zone id of tripleadev.com.br. No default."
  type        = string
}

variable "hostname" {
  description = "Public name of the portal."
  type        = string
  default     = "portal.tripleadev.com.br"
}

variable "allowed_emails" {
  description = "Individual addresses Access lets in. No default."
  type        = list(string)
}

variable "allowed_email_domains" {
  description = "Email domains Access lets in. No default."
  type        = list(string)
}

variable "session_duration" {
  description = "How long an Access login lasts."
  type        = string
  default     = "12h"
}
