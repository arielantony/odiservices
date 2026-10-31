PORT ?= 8000
VENV := api/.venv
# Stamp inside the venv: it is created, or synced again, whenever a
# requirements file is newer (git-ignored with the venv, so every worktree
# builds its own).
VENV_STAMP := $(VENV)/.synced
NVM  := . "$$HOME/.nvm/nvm.sh" && cd web && nvm use

.PHONY: help setup-api setup-web dev serve build-web test-web test-api test docker-build check-image compose-up compose-down infra-check deploy-check

help:
	@echo "make setup-api  Create api/.venv and install the pinned dependencies (uv)"
	@echo "make setup-web  Install the web dependencies (Node 24, Yarn 4)"
	@echo "make dev        Run the API and the web dev server"
	@echo "make serve      Run the API alone (no pages; see make dev)"
	@echo "make build-web  Build the web app into web/dist/"
	@echo "make test-web   Run the web tests"
	@echo "make test       Run the API and web tests"
	@echo "make docker-build  Build odiservices-api:local and odiservices-web:local"
	@echo "make check-image   Build both images and run the OPS-01 checks (needs Docker)"
	@echo "make compose-up    Run api and web in Docker on 127.0.0.1:8000 (needs Docker)"
	@echo "make compose-down  Stop and remove them"
	@echo "make deploy-check  Test the prod Compose override and deploy.sh (shellcheck when installed)"
	@echo "make infra-check   Format-check and validate infra/tofu (needs OpenTofu, no AWS credentials)"

$(VENV_STAMP): api/requirements.txt api/requirements-dev.txt
	cd api && { [ -d .venv ] || uv venv --python 3.14 .venv; } \
	&& VIRTUAL_ENV=$(CURDIR)/$(VENV) uv pip sync requirements.txt requirements-dev.txt
	@touch $@

setup-api: $(VENV_STAMP)

setup-web:
	corepack enable
	. "$$HOME/.nvm/nvm.sh" && cd web && nvm install && corepack enable && yarn install --immutable

# nvm use runs before the jobs start: sourced inside a background job, nvm
# can't find the installed versions.
dev: $(VENV_STAMP)
	@$(NVM) >/dev/null && cd .. && { \
	trap 'kill 0' INT TERM EXIT; \
	(cd api && .venv/bin/uvicorn server.main:create_app --factory --host 127.0.0.1 --port $(PORT) --reload --no-access-log) & \
	(cd web && yarn dev) & \
	wait; }

serve: $(VENV_STAMP)
	cd api && .venv/bin/uvicorn server.main:create_app --factory --host 127.0.0.1 --port $(PORT) --no-access-log

build-web:
	$(NVM) && yarn build

test-web:
	$(NVM) && yarn test --run

test-api: $(VENV_STAMP)
	cd api && .venv/bin/python -m pytest

test: test-api test-web

docker-build:
	docker build -t odiservices-api:local api
	docker build -t odiservices-web:local web

check-image:
	scripts/check-image.sh

compose-up:
	docker compose up --build --detach --wait

compose-down:
	docker compose down --remove-orphans

infra-check:
	cd ../infra/tofu && tofu fmt -check && tofu init -backend=false -input=false && tofu validate

deploy-check: $(VENV_STAMP)
	cd api && .venv/bin/python -m pytest tests/test_deploy_files.py
	@if command -v shellcheck >/dev/null; then shellcheck deploy/deploy.sh; else echo "shellcheck not installed, skipped"; fi
