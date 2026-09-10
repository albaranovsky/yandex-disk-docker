.DEFAULT_GOAL := help

.PHONY: help build pull setup token up down restart status sync test logs shell

help: ## Show help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

build: ## Build docker image
	docker compose build

pull: ## Pull latest docker image from registry
	docker compose pull

setup: ## Run interactive first-time setup wizard
	docker compose run --rm yandex-disk setup

token: ## Obtain OAuth token directly
	docker compose run --rm yandex-disk yadisk token

up: ## Start daemon in background
	docker compose up -d

down: ## Stop daemon
	docker compose down

restart: ## Restart daemon
	docker compose restart

status: ## Show sync status
	docker compose exec yandex-disk yadisk status

sync: ## Trigger manual synchronization
	docker compose exec yandex-disk yadisk sync

test: ## Run automated integration test suite
	./tests/test.sh

logs: ## Follow daemon logs
	docker compose logs -f

shell: ## Open shell inside container
	docker compose exec yandex-disk bash
