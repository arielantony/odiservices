#!/usr/bin/env bash
# Builds the portal image and runs the OPS-01 verification checks.
# Needs Docker. Exits non-zero on the first failed check.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE=odiservices-portal:local
NAME=odiservices-check-$$
PLANTED=(.env input/x.pdf outputs/x.json web/src/zz_check_touch.ts)
EMPTY_DIST=""

cleanup() {
  docker rm -f "$NAME" "$NAME-empty" >/dev/null 2>&1 || true
  for f in "${PLANTED[@]}"; do rm -f "$f"; done
  rmdir input outputs 2>/dev/null || true
  [ -z "$EMPTY_DIST" ] || rm -rf "$EMPTY_DIST"
}
trap cleanup EXIT

pass() { echo "ok   $1"; }
fail() { echo "FAIL $1" >&2; exit 1; }
check() { # check "<name>" <command...>
  local name=$1; shift
  "$@" >/dev/null 2>&1 && pass "$name" || fail "$name"
}

for f in "${PLANTED[@]}"; do
  [ ! -e "$f" ] || fail "$f already exists; remove it, the script plants and deletes it"
done

# Build with planted secrets and statements in the context.
mkdir -p input outputs
echo "PORTAL_ENV=dev" > .env
: > input/x.pdf
: > outputs/x.json
docker build --progress=plain -t "$IMAGE" . >/dev/null 2>&1 || fail "build"
pass "build"

check "planted .env, PDF, input and outputs are not in /app" \
  test -z "$(docker run --rm --entrypoint find "$IMAGE" /app \( -name '.env*' -o -name '*.pdf' -o -path '*/input*' -o -path '*/outputs*' \))"

# A change in web/src/ reuses both dependency layers.
echo "export {};" > web/src/zz_check_touch.ts
log=$(docker build --progress=plain -t "$IMAGE" . 2>&1) || fail "second build"
cached=$(echo "$log" | awk '
  /^#[0-9]+ \[.*RUN (yarn install|pip install)/ {step[$1]=1}
  /^#[0-9]+ CACHED/ {if ($1 in step) n++}
  END {print n+0}')
[ "$cached" = 2 ] || fail "second build: expected both install steps CACHED, got $cached"
rm -f web/src/zz_check_touch.ts
pass "second build reuses the dependency layers"

check "runs as uid 10001" test "$(docker run --rm "$IMAGE" id -u)" = 10001

tree=$(docker run --rm --entrypoint sh "$IMAGE" -c 'ls /app; ls /app/api; ls /app/web')
check "/app holds only api/server and web/dist" test "$tree" = "$(printf 'api\nweb\nserver\ndist')"

check "imports server.main with no PORTAL_* set" \
  docker run --rm --entrypoint python "$IMAGE" -c "import server.main"

PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
docker run -d --name "$NAME" -p "127.0.0.1:$PORT:8000" "$IMAGE" >/dev/null
BASE="http://127.0.0.1:$PORT"
for _ in $(seq 1 30); do curl -fs "$BASE/healthz" >/dev/null 2>&1 && break; sleep 1; done

check "container is running" test "$(docker inspect -f '{{.State.Status}}' "$NAME")" = running
check "GET /healthz" test "$(curl -s "$BASE/healthz")" = '{"status":"ok"}'
for path in / /categorizer/abc-123; do
  check "GET $path is the app shell" bash -c \
    "curl -si '$BASE$path' | head -1 | grep -q 200 && curl -si '$BASE$path' | grep -qi 'content-type: text/html' && curl -s '$BASE$path' | grep -q '<div id=\"root\">'"
done
asset=$(curl -s "$BASE/" | grep -oE '/assets/[^"]+\.js' | head -1)
check "hashed asset is immutable" bash -c \
  "curl -si '$BASE$asset' | grep -qi 'cache-control: public, max-age=31536000, immutable'"
for path in /.env /ask_pdf.py; do
  check "GET $path is 404" test "$(curl -s -o /dev/null -w '%{http_code}' "$BASE$path")" = 404
done

curl -s "$BASE/healthz?token=abc123" >/dev/null
sleep 1
logs=$(docker logs "$NAME" 2>&1)
check "log has JSON request events" bash -c "echo '$logs' | grep -q '^{.*request'"
check "log has no query string" bash -c "! echo '$logs' | grep -q 'abc123'"

for _ in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$NAME")" = healthy ] && break; sleep 1
done
check "health status is healthy" test "$(docker inspect -f '{{.State.Health.Status}}' "$NAME")" = healthy

# An empty dist makes prod refuse to start (BE-01).
EMPTY_DIST=$(mktemp -d); chmod 755 "$EMPTY_DIST"
docker run -d --name "$NAME-empty" -v "$EMPTY_DIST:/app/web/dist" "$IMAGE" >/dev/null
for _ in $(seq 1 30); do
  [ "$(docker inspect -f '{{.State.Status}}' "$NAME-empty")" = exited ] && break; sleep 1
done
check "empty dist: exits with code 1" test "$(docker inspect -f '{{.State.ExitCode}}' "$NAME-empty")" = 1
check "empty dist: says the frontend build is not found" \
  bash -c "docker logs '$NAME-empty' 2>&1 | grep -q 'Frontend build not found'"

echo "all image checks passed"
