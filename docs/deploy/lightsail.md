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

- `ssh_public_key`: the contents of your **public** key (here `~/.ssh/odiservices_lightsail.pub`; use the key you made for this host).
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

If Cloudflare is set up (section 7), take it down **first**: stop and remove
the service on the host (section 7.4), then `tofu destroy` in
`infra/cloudflare`. A tunnel with a live connector cannot be deleted.

## 6. Deploy

The portal is public only through Cloudflare (section 7). Before that, or to bypass it, reach it through an SSH tunnel (6.4).

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

## 7. Cloudflare (OPS-04)

The portal is public at `https://portal.tripleadev.com.br`, behind Cloudflare
Access (one-time PIN to the company domain). The origin has no open port: the
host dials out to Cloudflare through a tunnel. Port 22 stays the only open
port.

### 7.1 Configuration

```sh
cd infra/cloudflare
cp terraform.tfvars.example terraform.tfvars   # git-ignored: account id, zone id, allowed addresses and domains
cp backend.hcl.example backend.hcl             # git-ignored: set the AWS account id
set -a; . ~/.config/odiservices/cloudflare.env; set +a   # CLOUDFLARE_API_TOKEN, mode 600, never in chat
AWS_PROFILE=odiservices-tofu tofu init -backend-config=backend.hcl
AWS_PROFILE=odiservices-tofu tofu plan -out=plan.bin
```

Keep copies of `terraform.tfvars` and `backend.hcl` in `~/odiservices-backups/`.
The API token needs: Account › Cloudflare Tunnel, Access: Apps, Access:
Policies and Access: Organizations, Identity Providers, and Groups (all Write),
and Zone › DNS (Write).

### 7.2 Install the connector on the host

Update the checkout on the host (`deploy.sh <ref>`, section 6.2) so it holds
`install-cloudflared.sh`, then, from `infra/cloudflare` with the Cloudflare
and AWS variables loaded as above:

```sh
tofu output -raw tunnel_token | ssh -i <SSH_KEY_FILE> -o IdentitiesOnly=yes \
  deploy@<public_ip> /opt/odiservices/app/deploy/install-cloudflared.sh
```

The token travels only on standard input. Check:

```sh
ssh deploy@<public_ip> 'systemctl is-active cloudflared; systemctl is-enabled cloudflared'
curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  https://api.cloudflare.com/client/v4/accounts/<account_id>/cfd_tunnel/<tunnel_id> | jq -r .result.status
```

Expect `active`, `enabled` and `healthy`.

### 7.3 Rotate the token

`tofu apply -replace=cloudflare_zero_trust_tunnel_cloudflared.portal` creates a
new tunnel secret; repeat 7.2.

### 7.4 Take it offline

1. On the host: `sudo systemctl disable --now cloudflared`, then
   `sudo rm /etc/systemd/system/cloudflared.service /etc/odiservices/cloudflared.env`
   and `sudo systemctl daemon-reload`.
2. In `infra/cloudflare`: `tofu plan -destroy -out=destroy.bin`, then
   `tofu apply destroy.bin`. This removes the tunnel, the Access application,
   the policy, the login provider and the DNS record.

Do the host first: a tunnel that still has a connector cannot be deleted.

### 7.5 Sign out

`https://portal.tripleadev.com.br/cdn-cgi/access/logout`. The Access session
lasts 12 hours and ends only there.

### 7.6 Make the API verify the Access token (BE-23)

The API checks the Access token itself, so it needs two settings in
`/etc/odiservices/.env` on the host (root, `0600`). Neither is a secret, but
the file stays root-only and out of the repository.

1. On your machine, write the two lines to a private file. The AUD is read
   from the OpenTofu state (the Cloudflare token is not needed for this).
   Do not use the clipboard: copying the next command overwrites it.

   ```sh
   cd infra/cloudflare
   AUD=$(AWS_PROFILE=odiservices-tofu tofu output -raw access_aud)
   (umask 077; printf 'PORTAL_ACCESS_TEAM_DOMAIN=<team>.cloudflareaccess.com\nPORTAL_ACCESS_AUD=%s\n' "$AUD" \
     > ~/.config/odiservices/portal-access.env)
   ```

2. Write them on the host. `tee` runs under `sudo`, and the input comes from
   your file, so the `<` is on your machine (a `<` after `sudo` on the host
   would be opened by the `deploy` user and fail). `truncate` empties the
   file first, so run it only when the file holds nothing you need:

   ```sh
   ssh -i <SSH_KEY_FILE> -o IdentitiesOnly=yes deploy@<public_ip> \
     'sudo truncate -s 0 /etc/odiservices/.env && sudo tee -a /etc/odiservices/.env >/dev/null \
      && sudo grep -c "^PORTAL_ACCESS_" /etc/odiservices/.env' < ~/.config/odiservices/portal-access.env
   ```

   It must print `2`.

3. Recreate the `api` container, because it reads the file only when it is
   created. `deploy.sh` with the tag already running does not recreate it:

   ```sh
   ssh -i <SSH_KEY_FILE> -o IdentitiesOnly=yes deploy@<public_ip> \
     'cd /opt/odiservices/app && sudo env DEPLOY_TAG=<tag> docker compose -f docker-compose.yml \
      -f docker-compose.prod.yml up --detach --wait --force-recreate api \
      && sudo docker exec odiservices-api-1 env | grep -c "^PORTAL_ACCESS_"'
   ```

   It must print `2`. A deploy of a new tag creates the container again by
   itself.

Check it from the host. Both calls must answer `401`, because neither came
through Access:

```sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/session
curl -s -o /dev/null -w '%{http_code}\n' -H 'Cf-Access-Jwt-Assertion: aaa.bbb.ccc' http://127.0.0.1:8080/api/session
```

In the browser, after the PIN login, `https://portal.tripleadev.com.br/api/session`
shows `{"authenticated":true}`.

With the two settings missing the API still starts, `/healthz` stays up and
every other API route answers `503` (`auth_unavailable`). Two `503` on the
check above mean the container does not have the settings: count them as in
step 3.
