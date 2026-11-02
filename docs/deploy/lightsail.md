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

The first boot runs `launch.sh` and takes a few minutes. It is finished when
`/var/lib/odiservices-launch.done` exists; its log is
`/var/log/odiservices-launch.log`. Then:

```sh
ssh deploy@<public_ip> docker --version
```

Root and password logins are refused. The `ubuntu` account that Lightsail adds
still takes your key; leave it, and do not add keys to it.

## 4. State

The state lives in a private, versioned S3 bucket with locking (OPS-07). The
bucket is created once by `infra/tofu-bootstrap/`, whose own state is local and
git-ignored: keep a copy in `~/odiservices-backups/`.

**From a fresh checkout**

```sh
cd infra/tofu
cp terraform.tfvars.example terraform.tfvars   # git-ignored, see section 2
cp backend.hcl.example backend.hcl             # git-ignored, set the account id
AWS_PROFILE=odiservices-tofu tofu init -backend-config=backend.hcl
AWS_PROFILE=odiservices-tofu tofu plan         # "No changes" when nothing drifted
```

`terraform.tfvars` and `backend.hcl` stay local: keep a copy of both in
`~/odiservices-backups/`. The bucket allows TLS only, blocks public access and
encrypts at rest. The state holds the instance and its address, not a key.

- **Locking:** a second `plan` or `apply` fails with `Error acquiring the state
  lock` while one runs. If a run is killed and leaves the lock behind, check
  that nothing is running, then `tofu force-unlock <id>`.
- **Recovering a version:** the bucket keeps old versions for 90 days.
  `aws s3api list-object-versions --bucket <bucket> --prefix odiservices/lightsail/`
  lists them. To restore one, copy it back over the key:
  `aws s3api copy-object --bucket <bucket> --key odiservices/lightsail/terraform.tfstate --copy-source "<bucket>/odiservices/lightsail/terraform.tfstate?versionId=<id>"`.
  Then run `tofu plan` before anything else.
- **The bucket itself** has `prevent_destroy`. Removing it means emptying every
  version and removing that line first.

## 5. Destroy

```sh
tofu destroy
```

Removes the instance and releases the address. Nothing persists on the host.

## 6. Deploy

The portal is not public until OPS-04. You reach it through an SSH tunnel.

### 6.1 Deploy key (once)

The repository is private. On the host, as `deploy`:

```sh
ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```

Add the **public** key in the GitHub repository settings, Deploy keys, without
write access. The private key never leaves the host. Then:

```sh
ssh-keyscan github.com >> ~/.ssh/known_hosts
git clone git@github.com:arielantony/odiservices.git /opt/odiservices
```

### 6.2 Deploy or update

```sh
/opt/odiservices/app/deploy/deploy.sh <tag-or-commit>
```

The script refuses a dirty checkout, builds both images on the host, starts
them with `docker compose ... up --wait`, checks `/healthz` and `/`, and rolls
back to the previous tag on failure. It keeps the images of the last three
deploys. `/etc/odiservices/.env` is created empty (root, `0600`) if missing;
OPS-05 decides what goes in it.

### 6.3 Rollback

Run `deploy.sh` with the previous tag or commit.

### 6.3a A container that stays down

The restart policy is `unless-stopped`: Docker brings a crashed container back,
but not one stopped on purpose with `docker kill` or `docker stop`. To start it
again run `sudo docker start odiservices-api-1`, or run `deploy.sh` again.

### 6.4 Reach the portal

```sh
ssh -L 8080:127.0.0.1:8080 deploy@<public_ip>
```

Then open `http://127.0.0.1:8080` on your machine.

### 6.5 After a reboot

Docker starts at boot and `restart: unless-stopped` brings both containers
back with no step from you.
