# The state lives in the S3 bucket that infra/tofu-bootstrap creates (OPS-07).
# A backend block cannot read variables, so the values come from backend.hcl
# (git-ignored): tofu init -backend-config=backend.hcl
terraform {
  backend "s3" {}
}
