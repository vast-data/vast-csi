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
#     make e2e-nfs-stress 10.205.0.233
#     make cert-kubevirt 10.205.0.233
#     make cert-nfs 10.205.0.233 --list-only
#     make cert-kubevirt 10.205.0.233 --kubeconfig ~/.kube/config

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
E2E_PYTEST_FLAGS := -vv
PYTEST_E2E = cd "$(REPO_ROOT)" && VAST_ENDPOINT="$(VAST_ENDPOINT)" "$(PYTHON)" -m pytest $(E2E_PYTEST_FLAGS)

# One entry point per test suite: every e2e target names exactly one file, so a
# functional run can never pull in a stress or load suite by marker overlap.
E2E_NFS := tests/e2e/test_suites/test_nfs.py
E2E_NFS_STRESS := tests/e2e/test_suites/test_nfs_stress.py
E2E_NFS_LOAD := tests/e2e/test_suites/test_load_nfs.py
E2E_MTLS := tests/e2e/test_suites/test_mtls.py
E2E_BLOCK := tests/e2e/test_suites/test_block.py
E2E_BLOCK_STRESS := tests/e2e/test_suites/test_block_stress.py
E2E_COSI := tests/e2e/test_suites/test_cosi.py

# Capture everything after the target so `make cert-nfs 10.205.0.233 --list-only`
# does not fail with "No rule to make target".
ENDPOINT_TARGETS := e2e e2e-nfs e2e-nfs-stress e2e-nfs-load e2e-mtls e2e-block \
	e2e-block-stress e2e-cosi cert-nfs cert-block cert-kubevirt
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

.PHONY: help unit e2e e2e-nfs e2e-nfs-stress e2e-nfs-load e2e-mtls e2e-block \
	e2e-block-stress e2e-cosi cert-nfs cert-block cert-kubevirt

help: ## Show this help
	@echo "vast-csi tests"
	@echo
	@echo "Unit tests (no cluster / VAST required):"
	@echo "  make unit"
	@echo
	@echo "e2e and certification require a VAST management endpoint."
	@echo "Each e2e target runs exactly one suite; 'e2e' runs the three functional ones:"
	@echo "  make e2e-nfs <vast_endpoint>          # test_nfs.py"
	@echo "  make e2e-nfs-stress <vast_endpoint>   # test_nfs_stress.py"
	@echo "  make e2e-nfs-load <vast_endpoint>     # test_load_nfs.py"
	@echo "  make e2e-mtls <vast_endpoint>         # test_mtls.py"
	@echo "  make e2e-block <vast_endpoint>        # test_block.py"
	@echo "  make e2e-block-stress <vast_endpoint> # test_block_stress.py"
	@echo "  make e2e-cosi <vast_endpoint>         # test_cosi.py"
	@echo "  make e2e <vast_endpoint>              # nfs + block + cosi"
	@echo "  make cert-nfs <vast_endpoint>"
	@echo "  make cert-block <vast_endpoint>"
	@echo "  make cert-kubevirt <vast_endpoint>"
	@echo
	@echo "Extra arguments after the endpoint are forwarded to pytest or the cert scripts."
	@echo "e2e targets always run with -vv -s --log-cli-level=INFO (override via EXTRA_ARGS)."
	@echo "If they start with '-', put '--' before them so make does not eat the flags:"
	@echo "  make cert-nfs 10.205.0.233 -- --list-only"
	@echo "  make e2e-block 10.205.0.233 -- -k snapshot"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# -----------------------------------------------------------------------------
# Unit
# -----------------------------------------------------------------------------

unit: ## Run Python unit tests (no VAST endpoint)
	$(PYTEST) tests/unit -m 'not host_only' $(EXTRA_ARGS)

# -----------------------------------------------------------------------------
# e2e (pytest against a live Kubernetes cluster + VAST)
# -----------------------------------------------------------------------------

e2e: ## Run the functional suites (nfs + block + cosi; no mtls, stress, or load)
	$(need_endpoint)
	$(PYTEST_E2E) $(E2E_NFS) $(E2E_BLOCK) $(E2E_COSI) $(EXTRA_ARGS)

e2e-nfs: ## NFS functional suite (helm vastcsi)
	$(need_endpoint)
	$(PYTEST_E2E) $(E2E_NFS) $(EXTRA_ARGS)

e2e-nfs-stress: ## NFS wave stress suite (needs >= 2 nodes)
	$(need_endpoint)
	$(PYTEST_E2E) $(E2E_NFS_STRESS) $(EXTRA_ARGS)

e2e-nfs-load: ## NFS PVC churn load suite (long running)
	$(need_endpoint)
	$(PYTEST_E2E) $(E2E_NFS_LOAD) $(EXTRA_ARGS)

e2e-mtls: ## NFS mTLS suite (helm vastcsi, xprtsec=mtls)
	$(need_endpoint)
	$(PYTEST_E2E) $(E2E_MTLS) $(EXTRA_ARGS)

e2e-block: ## Block functional suite (helm vastblock)
	$(need_endpoint)
	$(PYTEST_E2E) $(E2E_BLOCK) $(EXTRA_ARGS)

e2e-block-stress: ## Block wave stress suite (needs >= 2 nodes)
	$(need_endpoint)
	$(PYTEST_E2E) $(E2E_BLOCK_STRESS) $(EXTRA_ARGS)

e2e-cosi: ## COSI functional suite (helm vastcosi)
	$(need_endpoint)
	$(PYTEST_E2E) $(E2E_COSI) $(EXTRA_ARGS)

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
