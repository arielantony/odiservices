variable "region" {
  description = "AWS region of the state bucket."
  type        = string
  default     = "us-east-2"
}

# No default on purpose: the name carries the AWS account id, which stays out of
# the repository (it goes in terraform.tfvars, which is git-ignored).
variable "bucket_name" {
  description = "Globally unique name of the state bucket, for example odiservices-tofu-state-<account-id>."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{2,62}$", var.bucket_name))
    error_message = "Use 3 to 63 lowercase letters, digits, dots or hyphens."
  }
}
