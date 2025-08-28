.SILENT:
.DEFAULT_GOAL := ci
.PHONY: docs

SHELL := /bin/bash

SRCDIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

GIT_COMMIT ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")
prepare:
	echo "git_commit = \"$(GIT_COMMIT)\"" > $(SRCDIR)/gpustack_runner/_version_appendix.py

deps: prepare
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

build: prepare
	@echo "+++ $@ +++"
	rm -rf dist
	uv build
	@echo "--- $@ ---"

DOCS_SERVE ?= false
docs:
	@echo "+++ $@ +++"
	rm -rf site
	uv run mkdocs build
	if [[ "$(DOCS_SERVE)" == "true" ]]; then \
		uv run mkdocs serve -o -w $(SRCDIR)/gpustack_runner; \
	fi
	@echo "--- $@ ---"

PACKAGE_NAMESPACE ?= gpustack
PACKAGE_REPOSITORY ?= runner
PACKAGE_TAG ?= cuda12.4-vllm0.10.0
package:
	@echo "+++ $@ +++"
	if [[ -z $$(command -v docker) ]]; then \
		echo "Docker is not installed. Please install Docker to use this target."; \
		exit 1; \
	fi
	if [[ -z $$(docker buildx inspect --builder "gpustack") ]]; then \
	    docker run --rm --privileged tonistiigi/binfmt:qemu-v9.2.2-52 --uninstall qemu-*; \
	    docker run --rm --privileged tonistiigi/binfmt:qemu-v9.2.2 --install all; \
	    docker buildx create \
	    	--name "gpustack" \
	    	--driver "docker-container" \
	    	--buildkitd-flags "--allow-insecure-entitlement security.insecure --allow-insecure-entitlement network.host" \
	    	--driver-opt "network=host,default-load=true,env.BUILDKIT_STEP_LOG_MAX_SIZE=-1,env.BUILDKIT_STEP_LOG_MAX_SPEED=-1" \
	    	--bootstrap; \
	fi
	INPUT_NAMESPACE=$(PACKAGE_NAMESPACE) \
	INPUT_REPOSITORY=$(PACKAGE_REPOSITORY) \
	INPUT_TAG=$(PACKAGE_TAG) \
		source $(SRCDIR)/pack/expand_matrix.sh
	for BUILD_JOB in $$(echo "$${BUILD_JOBS}" | jq -cr '.[]'); do \
	    JOB_BACKEND=$$(echo "$${BUILD_JOB}" | jq -r '.backend'); \
	    JOB_PLATFORM=$$(echo "$${BUILD_JOB}" | jq -r '.platform'); \
	    JOB_TARGET=$$(echo "$${BUILD_JOB}" | jq -r '.service'); \
	    JOB_TAG=$(PACKAGE_NAMESPACE)/$(PACKAGE_REPOSITORY):$$(echo "$${BUILD_JOB}" | jq -r '.platform_tag'); \
        JOB_ARGS=($$(echo "$${BUILD_JOB}" | jq -r '.args | map("--build-arg " + .) | join(" ")')); \
        echo "### building '$${JOB_TAG}' for target '$${JOB_TARGET}' on platform '$${JOB_PLATFORM}' using backend '$${JOB_BACKEND}'"; \
        set -x; \
        docker buildx build \
        	--pull \
            --allow network.host \
            --allow security.insecure \
        	--builder "gpustack" \
			--platform "$${JOB_PLATFORM}" \
			--target "$${JOB_TARGET}" \
			--tag "$${JOB_TAG}" \
			--file "$(SRCDIR)/pack/$${JOB_BACKEND}/Dockerfile" \
			$${JOB_ARGS[@]} \
			$(SRCDIR)/pack/$${JOB_BACKEND}; \
		set +x; \
	done
	@echo "--- $@ ---"

ci: deps install lint test clean build
