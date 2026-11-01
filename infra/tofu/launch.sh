#!/bin/bash
# First boot of the Lightsail instance (OPS-03). Lightsail runs this as root,
# once, as a shell script (it does not read cloud-config). No secret goes here.
set -euxo pipefail
exec > >(tee -a /var/log/odiservices-launch.log) 2>&1

export DEBIAN_FRONTEND=noninteractive
APT="apt-get -o DPkg::Lock::Timeout=300 -y"

# Access first, so a later failure still leaves a way in.
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
passwd -l deploy
echo 'deploy ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-deploy
chmod 0440 /etc/sudoers.d/90-deploy
install -d -m 0700 -o deploy -g deploy /home/deploy/.ssh
# shellcheck disable=SC2016  # OpenTofu fills the placeholder, the shell never expands it
echo '${ssh_public_key}' > /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 0600 /home/deploy/.ssh/authorized_keys

cat > /etc/ssh/sshd_config.d/50-odiservices.conf <<'CONF'
PasswordAuthentication no
PermitRootLogin no
KbdInteractiveAuthentication no
CONF
systemctl restart ssh

$APT update
$APT install ca-certificates curl git unattended-upgrades
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF

# Docker Engine and the Compose plugin from Docker's apt repository.
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck disable=SC1091  # /etc/os-release exists on the host
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
$APT update
$APT install docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker
usermod -aG docker deploy

# Runtime secrets (OPS-05) live here, root-only. The repository is private,
# so the owner clones it by hand with a read-only deploy key (OPS-03, 3.4).
install -d -m 0700 -o root -g root /etc/odiservices
install -d -m 0755 -o deploy -g deploy /opt/odiservices

touch /var/lib/odiservices-launch.done
