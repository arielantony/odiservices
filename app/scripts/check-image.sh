#!/usr/bin/env bash
# Builds the api and web images and runs the OPS-01 verification checks.
# Needs Docker. Exits non-zero on the first failed check.
set -euo pipefail
cd "$(dirname "$0")/.."

API_IMAGE=odiservices-api:local
WEB_IMAGE=odiservices-web:local
RUN=odiservices-check-$$
NET=$RUN-net
PLANTED=(api/.env web/.env api/input/x.pdf web/outputs/x.json
         web/src/zz_check_touch.ts api/server/zz_check_touch.py)

cleanup() {
  docker rm -f "$RUN-api" "$RUN-web" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  for f in "${PLANTED[@]}"; do rm -f "$f"; done
  rmdir api/input web/outputs 2>/dev/null || true
}
trap cleanup EXIT

pass() { echo "ok   $1"; }
fail() { echo "FAIL $1" >&2; exit 1; }
check() { # check "<name>" <command...>
  local name=$1; shift
  "$@" >/dev/null 2>&1 && pass "$name" || fail "$name"
}
equals() { # equals "<name>" <expected> <actual>
  [ "$3" = "$2" ] && pass "$1" || fail "$1 (expected '$2', got '$3')"
}
contains() { # contains "<name>" <needle> <haystack>
  case "$3" in *"$2"*) pass "$1" ;; *) fail "$1 (missing '$2')" ;; esac
}
lacks() { # lacks "<name>" <needle> <haystack>
  case "$3" in *"$2"*) fail "$1 (found '$2')" ;; *) pass "$1" ;; esac
}
wait_for() { # wait_for <seconds> <command...>
  local n=$1; shift
  for _ in $(seq 1 "$n"); do "$@" >/dev/null 2>&1 && return 0; sleep 1; done
  return 1
}
status_of() { docker inspect -f "{{$2}}" "$1"; }
healthy() { [ "$(status_of "$1" .State.Health.Status)" = healthy ]; }
code() { curl -s -o /dev/null -w '%{http_code}' "$1"; }
headers_ok() { # headers_ok "<name>" <url>
  local h; h=$(curl -si "$2" | tr -d '\r' | tr 'A-Z' 'a-z')
  contains "$1: nosniff" "x-content-type-options: nosniff" "$h"
  contains "$1: referrer-policy" "referrer-policy: same-origin" "$h"
  contains "$1: x-frame-options" "x-frame-options: deny" "$h"
}

for f in "${PLANTED[@]}"; do
  [ ! -e "$f" ] || fail "$f already exists; remove it, the script plants and deletes it"
done

# Build with planted secrets and statements in both contexts.
mkdir -p api/input web/outputs
echo "PORTAL_ENV=dev" > api/.env
echo "PORTAL_ENV=dev" > web/.env
: > api/input/x.pdf
: > web/outputs/x.json
docker build -q -t "$API_IMAGE" api >/dev/null || fail "build api"
docker build -q -t "$WEB_IMAGE" web >/dev/null || fail "build web"
pass "both images build"

for image in "$API_IMAGE" "$WEB_IMAGE"; do
  found=$(docker run --rm --entrypoint find "$image" / -xdev \
    \( -name '.env*' -o -name '*.pdf' -o -name input -o -name outputs -o -name x.json \) \
    -not -path '/proc/*' -not -path '/sys/*' -not -path '/usr/lib/*' -not -path '/usr/share/*' \
    -not -path '/etc/*' 2>/dev/null || true)
  equals "planted files are not in $image" "" "$found"
done

# A change only in web/src/ or api/server/ reuses that image's install layer.
cached_installs() { # cached_installs <context> <pattern>
  docker build --progress=plain -t "$3" "$1" 2>&1 | awk -v pat="$2" '
    $0 ~ "^#[0-9]+ \\[.*RUN " pat {step[$1]=1}
    /^#[0-9]+ CACHED/ {if ($1 in step) n++}
    END {print n+0}'
}
echo "export {};" > web/src/zz_check_touch.ts
equals "web: yarn install CACHED after a src change" 1 "$(cached_installs web 'yarn install' "$WEB_IMAGE")"
echo "x = 1" > api/server/zz_check_touch.py
equals "api: pip install CACHED after a server change" 1 "$(cached_installs api 'pip install' "$API_IMAGE")"
rm -f web/src/zz_check_touch.ts api/server/zz_check_touch.py

# api image
equals "api: runs as uid 10001" 10001 "$(docker run --rm --entrypoint id "$API_IMAGE" -u)"
equals "api: /app holds only server" server "$(docker run --rm --entrypoint ls "$API_IMAGE" /app)"
check "api: imports server.main with no PORTAL_* set" \
  docker run --rm --entrypoint python "$API_IMAGE" -c "import server.main"

docker network create "$NET" >/dev/null
docker run -d --name "$RUN-api" --network "$NET" --network-alias api "$API_IMAGE" >/dev/null
check "api: running" wait_for 30 test "$(status_of "$RUN-api" .State.Status)" = running
check "api: GET /healthz on its own network" wait_for 30 \
  docker run --rm --network "$NET" --entrypoint python "$API_IMAGE" -c \
  "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://api:8000/healthz').read() != b'{\"status\":\"ok\"}')"
equals "api: GET /api/nope is the JSON 404" \
  '{"error":{"code":"not_found","message":"Recurso não encontrado."}}' \
  "$(docker run --rm --network "$NET" --entrypoint python "$API_IMAGE" -c \
  "import urllib.request,urllib.error
try: urllib.request.urlopen('http://api:8000/api/nope')
except urllib.error.HTTPError as e: print(e.read().decode(), end='')")"
check "api: healthy within 60 seconds" wait_for 60 healthy "$RUN-api"

# web image, in front of the api container
equals "web: runs as uid 101" 101 "$(docker run --rm --entrypoint id "$WEB_IMAGE" -u)"
html=$(docker run --rm --entrypoint ls "$WEB_IMAGE" /usr/share/nginx/html | tr '\n' ' ')
equals "web: html root holds only the build" "50x.html assets index.html " "$html"

PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
docker run -d --name "$RUN-web" --network "$NET" -e API_UPSTREAM=api:8000 \
  -p "127.0.0.1:$PORT:8080" "$WEB_IMAGE" >/dev/null
BASE="http://127.0.0.1:$PORT"
check "web: serves /" wait_for 30 curl -fs "$BASE/"
check "web: nginx -t passes" docker exec "$RUN-web" nginx -t

for path in / /categorizer/abc-123; do
  h=$(curl -si "$BASE$path" | tr -d '\r')
  contains "web: GET $path is 200" "200 OK" "$(echo "$h" | head -1)"
  contains "web: GET $path is html" "Content-Type: text/html" "$h"
  contains "web: GET $path is the app shell" '<div id="root">' "$h"
  contains "web: GET $path is no-cache" "Cache-Control: no-cache" "$h"
done
asset=$(curl -s "$BASE/" | grep -oE '/assets/[^"]+\.js' | head -1)
contains "web: hashed asset is immutable" "public, max-age=31536000, immutable" \
  "$(curl -si "$BASE$asset")"
for path in /.env /ask_pdf.py /assets/missing.js; do
  equals "web: GET $path is 404" 404 "$(code "$BASE$path")"
done
headers_ok "web /" "$BASE/"
headers_ok "web asset" "$BASE$asset"
headers_ok "web 404" "$BASE/.env"
headers_ok "web /healthz" "$BASE/healthz"
PAGE_CSP="default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
API_CSP="default-src 'none'; frame-ancestors 'none'"
csp_is() { # csp_is "<name>" <expected> <url>: exactly one policy, equal to it
  local v; v=$(curl -si "$3" | tr -d '\r' | grep -i '^content-security-policy:' | sed 's/^[^:]*: //')
  equals "$1: one CSP, as specified" "$2" "$v"
}
csp_is "web /" "$PAGE_CSP" "$BASE/"
csp_is "web /categorizer" "$PAGE_CSP" "$BASE/categorizer"
csp_is "web asset" "$PAGE_CSP" "$BASE$asset"
csp_is "web /.env" "$PAGE_CSP" "$BASE/.env"
csp_is "web /healthz" "$API_CSP" "$BASE/healthz"
csp_is "web /api/nope" "$API_CSP" "$BASE/api/nope"
equals "api: direct /api/nope carries the API CSP" "$API_CSP" "$(docker run --rm --network "$NET" --entrypoint python "$API_IMAGE" -c \
  "import urllib.request,urllib.error
try: urllib.request.urlopen('http://api:8000/api/nope')
except urllib.error.HTTPError as e: print(e.headers['Content-Security-Policy'], end='')")"
lacks "web: the shell names no outside host" "https://" "$(curl -s "$BASE/")"
check "web: the build ships woff2 fonts" bash -c "docker run --rm --entrypoint ls '$WEB_IMAGE' /usr/share/nginx/html/assets | grep -q woff2"
equals "web: GET /healthz is proxied" '{"status":"ok"}' "$(curl -s "$BASE/healthz")"
equals "web: GET /api/nope is the API's 404" \
  '{"error":{"code":"not_found","message":"Recurso não encontrado."}}' "$(curl -s "$BASE/api/nope")"

curl -s "$BASE/healthz?token=abc123" >/dev/null
sleep 1
lacks "web: log has no query string" abc123 "$(docker logs "$RUN-web" 2>&1)"
lacks "api: log has no query string" abc123 "$(docker logs "$RUN-api" 2>&1)"
contains "api: log has JSON request events" '"event": "request"' "$(docker logs "$RUN-api" 2>&1)"

check "web: healthy within 60 seconds" wait_for 60 healthy "$RUN-web"
docker stop "$RUN-api" >/dev/null
equals "web: / is 200 with api stopped" 200 "$(code "$BASE/")"
# The resolver cache (10s) may still hold the stopped container's address.
bad_gateway() { [ "$(code "$BASE/healthz")" = 502 ]; }
check "web: /healthz is 502 with api stopped" wait_for 20 bad_gateway
docker restart "$RUN-web" >/dev/null
check "web: healthy with api stopped" wait_for 60 healthy "$RUN-web"

echo "all image checks passed"
