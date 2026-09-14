.DEFAULT_GOAL := help

IMAGE ?= yandex-disk:latest

.PHONY: help build pull setup token up down restart status sync publish unpublish test lint logs shell

help: ## Show help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

build: ## Build docker image
	docker compose build

pull: ## Pull latest docker image from registry
	docker compose pull

setup: ## Run interactive first-time setup wizard
	docker compose run --rm yandex-disk yadisk setup

token: ## Obtain OAuth token directly
	docker compose run --rm yandex-disk yadisk token

up: ## Start daemon in background
	docker compose up -d

down: ## Stop daemon
	docker compose down

restart: ## Restart daemon
	docker compose restart

status: ## Show sync status (use ARGS="--last" for recent files)
	docker compose exec yandex-disk yadisk status $(ARGS)

sync: ## Trigger manual synchronization
	docker compose exec yandex-disk yadisk sync

publish: ## Publish file or folder (make publish FILE=path)
	@test -n "$(FILE)" || { echo "Usage: make publish FILE=<path>"; exit 1; }
	docker compose exec yandex-disk yadisk publish "$(FILE)"

unpublish: ## Revoke public link (make unpublish FILE=path)
	@test -n "$(FILE)" || { echo "Usage: make unpublish FILE=<path>"; exit 1; }
	docker compose exec yandex-disk yadisk unpublish "$(FILE)"

test: ## Run automated integration test suite (IMAGE=...)
	./tests/test.sh $(IMAGE)

lint: ## Lint Dockerfile and shell scripts with Hadolint and ShellCheck
	docker run --rm -i hadolint/hadolint:latest < Dockerfile
	docker run --rm -v "$$(pwd):/mnt" -w /mnt koalaman/shellcheck:stable entrypoint.sh yadisk tests/test.sh

logs: ## Follow daemon logs
	docker compose logs -f

shell: ## Open shell inside container
	docker compose exec yandex-disk bash
