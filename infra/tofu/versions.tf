terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.71.0"
    }
  }
}

# Credentials come from the AWS CLI profile or SSO session on the operator's
# machine. Nothing in this repository names a key.
provider "aws" {
  region = var.region
}
