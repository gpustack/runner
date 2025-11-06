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

CLEAN_UNTRACKED ?= false
clean:
	@echo "+++ $@ +++"
	uv run pyclean -v $(SRCDIR)
	rm -rf dist
	if [[ "$(CLEAN_UNTRACKED)" == "true" ]]; then \
		git clean -f .; \
	fi
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

docs:
	@echo "+++ $@ +++"
	rm -rf site
	uv run mkdocs build
	@echo "--- $@ ---"

docs-online: docs
	@echo "+++ $@ +++"
	uv run mkdocs serve -o -w $(SRCDIR)/gpustack_runner
	@echo "--- $@ ---"


PACKAGE_NAMESPACE ?= gpustack
PACKAGE_REPOSITORY ?= runner
PACKAGE_CACHE_REPOSITORY ?= runner-build-cache
PACKAGE_TARGET ?= services
PACKAGE_POST_OPERATION ?=
PACKAGE_TAG ?= cuda12.4-vllm0.10.0
PACKAGE_WITH_CACHE ?= true
PACKAGE_PUSH ?= false
PACKAGE_CACHE_PUSH ?= false
package:
	@echo "+++ $@ +++"
	if [[ -z $$(command -v docker) ]]; then \
		echo "[FATAL] Docker is not installed. Please install Docker to use this target."; \
		exit 1; \
	fi
	if [[ -z $$(docker buildx inspect --builder "gpustack" 2>/dev/null) ]]; then \
		echo "[INFO] Creating new buildx builder 'gpustack'"; \
		docker run --rm --privileged tonistiigi/binfmt:qemu-v9.2.2-52 --uninstall qemu-*; \
		docker run --rm --privileged tonistiigi/binfmt:qemu-v9.2.2-52 --install all; \
		docker buildx create \
			--name "gpustack" \
			--driver "docker-container" \
			--driver-opt "network=host,default-load=true,env.BUILDKIT_STEP_LOG_MAX_SIZE=-1,env.BUILDKIT_STEP_LOG_MAX_SPEED=-1" \
			--buildkitd-flags "--allow-insecure-entitlement=security.insecure --allow-insecure-entitlement=network.host --oci-worker-net=host --oci-worker-gc-keepstorage=204800" \
			--bootstrap; \
	fi
	INPUT_NAMESPACE=$(PACKAGE_NAMESPACE) \
	INPUT_REPOSITORY=$(PACKAGE_REPOSITORY) \
	INPUT_POST_OPERATION=$(PACKAGE_POST_OPERATION) \
	INPUT_TARGET=$(PACKAGE_TARGET) \
	INPUT_TAG=$(PACKAGE_TAG) \
		source $(SRCDIR)/pack/expand_matrix.sh; \
	for BUILD_JOB in $$(echo "$${BUILD_JOBS}" | jq -cr '.[]'); do \
		JOB_BACKEND=$$(echo "$${BUILD_JOB}" | jq -r '.backend'); \
		JOB_PLATFORM=$$(echo "$${BUILD_JOB}" | jq -r '.platform'); \
		JOB_TARGET=$$(echo "$${BUILD_JOB}" | jq -r '.service'); \
		JOB_TAG=$(PACKAGE_NAMESPACE)/$(PACKAGE_REPOSITORY):$$(echo "$${BUILD_JOB}" | jq -r '.platform_tag'); \
		JOB_ARGS=($$(echo "$${BUILD_JOB}" | jq -r '.args | map("--build-arg " + .) | join(" ")')); \
		JOB_PLATFORM_CACHE=$$(echo "$${BUILD_JOB}" | jq -r '.platform_tag_cache | join(" ")'); \
		JOB_EXTRA_ARGS=(); \
		if [[ "$(PACKAGE_WITH_CACHE)" == "true" ]]; then \
			for TAG_CACHE in $${JOB_PLATFORM_CACHE}; do \
				JOB_EXTRA_ARGS+=("--cache-from=type=registry,ref=gpustack/runner-build-cache:$${TAG_CACHE}"); \
			done; \
		fi; \
		if [[ "$(PACKAGE_PUSH)" == "true" ]] || [[ "$(PACKAGE_CACHE_PUSH)" == "true" ]]; then \
			for TAG_CACHE in $${JOB_PLATFORM_CACHE}; do \
				JOB_EXTRA_ARGS+=("--cache-to=type=registry,ignore-error=true,mode=max,compression=gzip,ref=$(PACKAGE_NAMESPACE)/$(PACKAGE_CACHE_REPOSITORY):$${TAG_CACHE}"); \
			done; \
		fi; \
		if [[ "$(PACKAGE_PUSH)" == "true" ]]; then \
			JOB_EXTRA_ARGS+=("--push"); \
		fi; \
		JOB_LOCATION=$(SRCDIR)/pack/$${JOB_BACKEND}; \
		if [[ -n "$(PACKAGE_POST_OPERATION)" ]]; then \
		    JOB_LOCATION=$(SRCDIR)/pack/.post_operation/$(PACKAGE_POST_OPERATION)/$${JOB_BACKEND}; \
		fi; \
		echo "[INFO] Building '$${JOB_TAG}' for target '$${JOB_TARGET}' on platform '$${JOB_PLATFORM}' using backend '$${JOB_BACKEND}'"; \
		set -x; \
		docker buildx build \
			--allow network.host \
			--allow security.insecure \
			--builder "gpustack" \
			--platform "$${JOB_PLATFORM}" \
			--target "$${JOB_TARGET}" \
			--tag "$${JOB_TAG}" \
			--file "$${JOB_LOCATION}/Dockerfile" \
			--attest "type=provenance,disabled=true" \
			--attest "type=sbom,disabled=true" \
			--ulimit nofile=65536:65536 \
			--shm-size 16G \
			--progress plain \
			$${JOB_ARGS[@]} \
			$${JOB_EXTRA_ARGS[@]} \
			$${JOB_LOCATION}; \
		set +x; \
	done
	@echo "--- $@ ---"

ci: deps install lint test clean build
