.SILENT:
.DEFAULT_GOAL := ci

SHELL := /bin/bash

SRCDIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

deps:
	@echo "+++ $@ +++"
	uv sync --all-packages
	uv lock
	uv tree
	@echo "--- $@ ---"

INSTALL_HOOKS ?= true
install: deps
	@echo "+++ $@ +++"
	if [[ "$(INSTALL_HOOKS)" == "true" ]]; then \
		uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push; \
	else \
		echo "Skipping pre-commit hook installation."; \
	fi
	@echo "--- $@ ---"

clean:
	@echo "+++ $@ +++"
	uv run pyclean -v $(SRCDIR)
	rm -rf dist
	@echo "--- $@ ---"

LINT_DIRTY ?= false
lint:
	@echo "+++ $@ +++"
	uv run pre-commit run --all-files --show-diff-on-failure
	if [[ "$(LINT_DIRTY)" == "true" ]]; then \
		if [[ -n $$(git status --porcelain) ]]; then \
			echo "Code tree is dirty."; \
			git diff --exit-code; \
		fi; \
	fi
	@echo "--- $@ ---"

test:
	@echo "+++ $@ +++"
	uv run pytest
	@echo "--- $@ ---"

build:
	@echo "+++ $@ +++"
	rm -rf dist
	uv build
	@echo "--- $@ ---"

ci: deps install lint test build
