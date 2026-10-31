# Runbook — AWS Lightsail (OPS-03)

One Lightsail instance in `us-east-2` (Ohio), created with OpenTofu. The portal
is **not public**: only SSH is open, and you reach the portal through a tunnel
until Cloudflare (OPS-04). The spec is
`docs/specs/deploy/OPS-03-lightsail-deploy.md`.

## 1. Credentials

Use an AWS CLI profile or an SSO session on your own machine, with Lightsail
permissions only (the managed policy `AmazonLightsailFullAccess`). Never put a
key in this repository, a `.tfvars` file or a shell history.

```sh
aws sts get-caller-identity   # confirms the profile works
export AWS_PROFILE=<your profile>
```

## 2. Configure

```sh
cd infra/tofu
cp terraform.tfvars.example terraform.tfvars   # git-ignored
```

Edit `terraform.tfvars`:

- `ssh_public_key`: the contents of your **public** key (`~/.ssh/id_ed25519.pub`).
- `ssh_allowed_cidrs`: your address as `x.x.x.x/32`. `0.0.0.0/0` is rejected.

Check the plan id first: `aws lightsail get-bundles --region us-east-2`, and
confirm `medium_3_0` is the dual-stack 4 GB plan. If it is not, set
`bundle_id` in `terraform.tfvars` and tell the spec's owner.

## 3. Create

```sh
tofu init
tofu plan     # creates a key pair, an instance, a static IP, its attachment and the port rule. No destroy
tofu apply
tofu output ssh_command
```

The first boot (cloud-init) takes a few minutes. Then:

```sh
ssh deploy@<public_ip> docker --version
```

Root and password logins are refused. The `ubuntu` account that Lightsail adds
still takes your key; leave it, and do not add keys to it.

## 4. State

The state is **local** (`infra/tofu/terraform.tfstate`) and git-ignored. It
holds the instance and its address, not a key, but treat it as sensitive:

- Copy it somewhere safe outside the repository after every `apply`.
- Run `apply` from one machine only.
- A later item moves it to S3.

## 5. Destroy

```sh
tofu destroy
```

Removes the instance and releases the address. Nothing persists on the host.

## 6. Deploy

Added by step 2 of OPS-03 (deploy key, first deploy, update, rollback and the
tunnel).
