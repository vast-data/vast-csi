# Test entry points for vast-csi (unit, e2e, Red Hat certification).
#
# Cluster-backed targets take a required VAST management endpoint as the first
# extra argument
#
#   Usage:
#     make <target> <vast_endpoint> [options]
#
#   Arguments:
#     <vast_endpoint> - Required for e2e and certification. VAST VMS IP or FQDN.
#
#   Extra options after the endpoint are forwarded to pytest / the cert scripts.
#
#   Examples:
#     make unit
#     make e2e-nfs 10.205.0.233
#     make cert-kubevirt 10.205.0.233
#     make cert-nfs 10.205.0.233 --list-only
#     make cert-all 10.205.0.233 --kubeconfig ~/.kube/config

SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

# This Makefile lives in tests/, so CURDIR is the tests dir and the repo root is
# one level up. Run it from tests/ or via `make -C tests <target>`.
TESTS_DIR := $(CURDIR)
REPO_ROOT := $(abspath $(CURDIR)/..)
CURRENT_TARGET := $(firstword $(MAKECMDGOALS))

ifeq ($(wildcard $(REPO_ROOT)/.venv/bin/python),)
PYTHON := python3
else
PYTHON := $(REPO_ROOT)/.venv/bin/python
endif

CERT_DIR := $(TESTS_DIR)/certification/redhat-e2e
PYTEST := cd "$(REPO_ROOT)" && "$(PYTHON)" -m pytest
# tests/lib/rest/session.py reads the endpoint from VAST_ENDPOINT, so it has to be
# exported for the pytest process, not for the leading cd.
# Recursive '=' on purpose: VAST_ENDPOINT is assigned further down.
PYTEST_E2E = cd "$(REPO_ROOT)" && VAST_ENDPOINT="$(VAST_ENDPOINT)" "$(PYTHON)" -m pytest

# Capture everything after the target so `make cert-nfs 10.205.0.233 --list-only`
# does not fail with "No rule to make target".
ENDPOINT_TARGETS := e2e e2e-nfs e2e-mtls e2e-block e2e-cosi cert-nfs cert-block cert-kubevirt cert-all
ARG_TARGETS := unit $(ENDPOINT_TARGETS)

ifneq ($(filter $(CURRENT_TARGET),$(ARG_TARGETS)),)
  runargs := $(wordlist 2, $(words $(MAKECMDGOALS)), $(MAKECMDGOALS))
  $(foreach arg,$(runargs),$(eval $(arg):;@true))
endif

ifneq ($(filter $(CURRENT_TARGET),$(ENDPOINT_TARGETS)),)
  VAST_ENDPOINT := $(word 1,$(runargs))
  EXTRA_ARGS := $(wordlist 2, $(words $(runargs)), $(runargs))
else
  EXTRA_ARGS := $(runargs)
endif

define need_endpoint
	@if [ -z "$(VAST_ENDPOINT)" ]; then \
		echo "Usage: make $(CURRENT_TARGET) <vast_endpoint> [options]"; \
		echo "   Example: make $(CURRENT_TARGET) 10.205.0.233"; \
		exit 1; \
	fi
endef

.PHONY: help unit e2e e2e-nfs e2e-mtls e2e-block e2e-cosi cert-nfs cert-block cert-kubevirt cert-all

help: ## Show this help
	@echo "vast-csi tests"
	@echo
	@echo "Unit tests (no cluster / VAST required):"
	@echo "  make unit"
	@echo
	@echo "e2e and certification require a VAST management endpoint:"
	@echo "  make e2e-nfs <vast_endpoint>"
	@echo "  make e2e-mtls <vast_endpoint>"
	@echo "  make e2e-block <vast_endpoint>"
	@echo "  make e2e-cosi <vast_endpoint>"
	@echo "  make e2e <vast_endpoint>              # nfs + block + cosi"
	@echo "  make cert-nfs <vast_endpoint>"
	@echo "  make cert-block <vast_endpoint>"
	@echo "  make cert-kubevirt <vast_endpoint>"
	@echo "  make cert-all <vast_endpoint>"
	@echo
	@echo "Extra arguments after the endpoint are forwarded to pytest or the cert scripts."
	@echo "If they start with '-', put '--' before them so make does not eat the flags:"
	@echo "  make cert-nfs 10.205.0.233 -- --list-only"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# -----------------------------------------------------------------------------
# Unit
# -----------------------------------------------------------------------------

unit: ## Run Python unit tests (no VAST endpoint)
	$(PYTEST) tests/unit -m 'not host_only' $(EXTRA_ARGS)

# -----------------------------------------------------------------------------
# e2e (pytest against a live Kubernetes cluster + VAST)
# -----------------------------------------------------------------------------

e2e: ## Run all e2e suites (nfs, block, cosi; excludes mtls)
	$(need_endpoint)
	$(PYTEST_E2E) tests/e2e -m '(nfs and not mtls) or block or cosi' $(EXTRA_ARGS)

e2e-nfs: ## Run NFS e2e (helm vastcsi)
	$(need_endpoint)
	$(PYTEST_E2E) tests/e2e -m 'nfs and not mtls' $(EXTRA_ARGS)

e2e-mtls: ## Run NFS mTLS e2e (helm vastcsi, xprtsec=mtls)
	$(need_endpoint)
	$(PYTEST_E2E) tests/e2e -m mtls $(EXTRA_ARGS)

e2e-block: ## Run block e2e (helm vastblock)
	$(need_endpoint)
	$(PYTEST_E2E) tests/e2e -m block $(EXTRA_ARGS)

e2e-cosi: ## Run COSI e2e (helm vastcosi)
	$(need_endpoint)
	$(PYTEST_E2E) tests/e2e -m cosi $(EXTRA_ARGS)

# -----------------------------------------------------------------------------
# Red Hat / OpenShift certification
# -----------------------------------------------------------------------------

cert-nfs: ## OpenShift CSI certification (NFS)
	$(need_endpoint)
	cd "$(REPO_ROOT)" && "$(PYTHON)" "$(CERT_DIR)/run_certification.py" nfs \
		--vast-endpoint "$(VAST_ENDPOINT)" $(EXTRA_ARGS)

cert-block: ## OpenShift CSI certification (block)
	$(need_endpoint)
	cd "$(REPO_ROOT)" && "$(PYTHON)" "$(CERT_DIR)/run_certification.py" block \
		--vast-endpoint "$(VAST_ENDPOINT)" $(EXTRA_ARGS)

cert-kubevirt: ## KubeVirt storage checkup on NFS
	$(need_endpoint)
	cd "$(REPO_ROOT)" && "$(PYTHON)" "$(CERT_DIR)/run_certification.py" kubevirt \
		--vast-endpoint "$(VAST_ENDPOINT)" $(EXTRA_ARGS)

cert-all: ## NFS + block + KubeVirt certification
	$(need_endpoint)
	cd "$(REPO_ROOT)" && "$(PYTHON)" "$(CERT_DIR)/run_certification.py" all \
		--vast-endpoint "$(VAST_ENDPOINT)" $(EXTRA_ARGS)
