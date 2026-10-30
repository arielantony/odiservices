PORT ?= 8000
NVM  := . "$$HOME/.nvm/nvm.sh" && cd web && nvm use

.PHONY: help setup-web dev serve build-web test-web test-api test

help:
	@echo "make setup-web  Install the web dependencies (Node 24, Yarn 4)"
	@echo "make dev        Run the API and the web dev server"
	@echo "make serve      Run the API alone, serving web/dist/ (like prod)"
	@echo "make build-web  Build the web app into web/dist/"
	@echo "make test-web   Run the web tests"
	@echo "make test       Run the API and web tests"

setup-web:
	corepack enable
	. "$$HOME/.nvm/nvm.sh" && cd web && nvm install && corepack enable && yarn install --immutable

dev:
	@trap 'kill 0' INT TERM EXIT; \
	(cd api && .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port $(PORT) --reload --no-access-log) & \
	$(NVM) >/dev/null && yarn dev & \
	wait

serve:
	cd api && .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port $(PORT) --no-access-log

build-web:
	$(NVM) && yarn build

test-web:
	$(NVM) && yarn test --run

test-api:
	cd api && .venv/bin/python -m pytest

test: test-api test-web
