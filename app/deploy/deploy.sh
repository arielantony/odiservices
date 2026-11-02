#!/usr/bin/env bash
# Deploy a git ref on the Lightsail host (OPS-03). Run as the deploy user:
#   /opt/odiservices/app/deploy/deploy.sh <ref>
# Prints no environment variable, no env file content and no request data.
set -euo pipefail

REF="${1:?usage: deploy.sh <git ref>}"
ENV_FILE=/etc/odiservices/.env
BASE="http://127.0.0.1:8080"

cd "$(dirname "${BASH_SOURCE[0]}")/.."
# Compose reads env_file on the client side, and /etc/odiservices/.env is root-only
# (0600), so compose runs under sudo. Builds and git stay as the deploy user.
# The hash of the env file goes into a label of the api container
# (docker-compose.prod.yml), so a change to the file recreates the container even
# when the tag is the same. Only the hash is used; the content is never printed.
compose() {
  local tag="$1" env_hash; shift
  env_hash="$(sudo sha256sum "$ENV_FILE" | cut -d' ' -f1)"
  sudo env DEPLOY_TAG="$tag" ENV_SHA256="$env_hash" docker compose -f docker-compose.yml -f docker-compose.prod.yml "$@"
}

if [ -n "$(git status --porcelain)" ]; then
  echo "refusing to deploy: the checkout is dirty" >&2
  exit 1
fi

# The test runs under sudo: the directory is root-only, and as the deploy user
# `-e` reports a missing file and the install below would empty the real one.
if ! sudo test -e "$ENV_FILE"; then
  sudo install -m 0600 -o root -g root /dev/null "$ENV_FILE"
fi

git fetch --tags origin
git checkout --detach "$REF"
TAG="$(git rev-parse --short HEAD)"

previous="$(docker inspect --format '{{ index .Config.Image }}' odiservices-web-1 2>/dev/null | cut -d: -f2 || true)"

docker build -t "odiservices-api:${TAG}" api
docker build -t "odiservices-web:${TAG}" web

healthy() {
  curl -fsS "${BASE}/healthz" > /dev/null && curl -fsS "${BASE}/" > /dev/null
}

if compose "$TAG" up --detach --wait && healthy; then
  echo "deployed ${TAG}"
else
  echo "deploy of ${TAG} failed" >&2
  if [ -n "$previous" ] && [ "$previous" != "$TAG" ]; then
    echo "rolling back to ${previous}" >&2
    compose "$previous" up --detach --wait
  fi
  exit 1
fi

# Keep the images of the last three deploys, and never the ones in use or the
# rollback target, even when they are old (an older commit deployed again keeps
# its old creation date and would sort last).
for svc in api web; do
  docker images "odiservices-${svc}" --format '{{.Tag}}' \
    | grep -vx -e current -e local -e "$TAG" -e "${previous:-current}" | tail -n +4 \
    | xargs -r -I{} docker rmi "odiservices-${svc}:{}" || true
done
