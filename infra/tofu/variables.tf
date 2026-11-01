variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-2"
}

variable "availability_zone" {
  description = "Availability zone inside the region."
  type        = string
  default     = "us-east-2a"
}

variable "bundle_id" {
  description = "Lightsail plan. medium_3_0 is the dual-stack 4 GB plan."
  type        = string
  default     = "medium_3_0"
}

variable "blueprint_id" {
  description = "Lightsail OS image."
  type        = string
  default     = "ubuntu_24_04"
}

variable "ssh_public_key" {
  description = "The operator's public SSH key (the private key never enters OpenTofu)."
  type        = string
}

variable "ssh_allowed_cidrs" {
  description = "CIDR blocks allowed to reach TCP 22. Never the whole internet."
  type        = list(string)

  validation {
    condition     = length(var.ssh_allowed_cidrs) > 0 && !contains(var.ssh_allowed_cidrs, "0.0.0.0/0") && !contains(var.ssh_allowed_cidrs, "::/0")
    error_message = "ssh_allowed_cidrs must list at least one CIDR and must not include 0.0.0.0/0 or ::/0."
  }
}
