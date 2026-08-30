.EXPORT_ALL_VARIABLES:
SHELL := /usr/bin/env bash
CURRENT_TARGET := $(firstword $(MAKECMDGOALS))
GIT_TAG=$(shell git describe --tags --abbrev=0)
GIT_COMMIT := $(shell git rev-parse --short=8 HEAD)
UNAME_S := $(shell uname -s)


OPERATOR_VERSION := $(shell awk '/^version:/ { print $$2; exit }' $(CURDIR)/charts/vastcsi-operator/Chart.yaml | sed 's/"//g')
# Include content of .env file as environment for all make commands (if such file exists)
# For better usability you can create .env file and specify necessary variable here. For instance
# PIPE=12345
# ....
MAKEENV=/tmp/.csimakeenv
$(shell echo '' > ${MAKEENV} && chmod 777 ${MAKEENV})
IGNORE := $(shell [ -f .env ] && env `(cat .env | xargs)` | sed 's/=/:=/' | sed 's/^/export /' > ${MAKEENV})
include ${MAKEENV}

# Variables for running dev build via skaffold
ENDPOINT ?= localhost
DEV_USERNAME ?= admin
DEV_PASSWORD ?= 123456
DEV_VIP_POOL ?= vippool-1
DEV_VIEW_POLICY ?= default
DEV_SUBSYSTEM ?= vastcsi
ifeq ($(UNAME_S),Darwin)
	MINIKUBE_DRIVER ?= qemu2
else
	MINIKUBE_DRIVER ?= kvm2
endif

ifndef IMG
    IMG := $(DOCKER_REGISTRY)/dev/vast-csi
endif
ifndef CSI_PLUGIN_IMG
    CSI_PLUGIN_IMG := $(DOCKER_REGISTRY)/dev/vast-csi
endif
ifndef CHANNEL
CHANNEL := "stable"
endif
ifndef NAMESPACE
NAMESPACE := "vast-csi"
endif
ifndef IMG_PULL_SECRET
IMG_PULL_SECRET := "regcred"
endif
# Set default values for tags
# in simplest case, only PIPE is required eg. export PIPE=xxxxxx. Other tags will be built upon this one:
# CSI_TAG=xxxxxx
# EXTENSIONS_TAG=xxxxxx-extensions
# OPERATOR_TAG=xxxxxx-operator
# OPERATOR_BUNDLE_TAG=xxxxxx-operator-bundle
# In more complex scenarios, you can specify all tags
# separately eg export CSI_TAG=vvvvvv OPERATOR_TAG=yyyyy-operator etc.
CSI_TAG := $(if $(CSI_TAG),$(CSI_TAG),$(PIPE))
EXTENSIONS_IMG := $(if $(EXTENSIONS_IMG),$(EXTENSIONS_IMG),$(CSI_PLUGIN_IMG))
EXTENSIONS_TAG := $(if $(EXTENSIONS_TAG),$(EXTENSIONS_TAG),$(if $(findstring @sha256:,$(CSI_TAG)),,$(if $(CSI_TAG),$(CSI_TAG)-extensions)))
OPERATOR_TAG := $(if $(OPERATOR_TAG),$(OPERATOR_TAG),$(if $(PIPE),$(PIPE)-operator))
OPERATOR_BUNDLE_TAG := $(if $(OPERATOR_BUNDLE_TAG),$(OPERATOR_BUNDLE_TAG),$(if $(PIPE),$(PIPE)-operator-bundle))
# Define the script for checking required environment variables
define check_required_env =
	@if [ -n "$$CURRENT_TARGET" ]; then \
		printf "\033[32m[%s]\033[0m\n" "$$CURRENT_TARGET"; \
	fi; \
	missing_vars=0; \
	for var in $(strip $1); do \
		if [ -z "$${!var}" ]; then \
			printf "\033[31m!\033[36m%-30s\033[0m \033[31m<missing>\033[0m\n" $$var; \
			missing_vars=1; \
		else \
			printf "\033[31m!\033[36m%-30s\033[0m %s\n" $$var "$${!var}"; \
		fi; \
	done; \
	if [ $$missing_vars -ne 0 ]; then \
		echo "Please ensure all required environment variables are set and not empty."; \
		exit 1; \
	fi;
endef

# Define the script for checking non-required environment variables (for informational purposes)
define check_non_required_env =
    for var in $(strip $1); do \
        if [ ! -z "$${!var}" ]; then \
            printf " \033[36m%-30s\033[0m %s\n" $$var "$${!var}"; \
        fi; \
    done
endef

.PHONY: check_required_env check_non_required_env


######################
# CSI OPERATOR
######################
operator-build: ## Build operator docker image
	@$(call check_required_env,IMG OPERATOR_TAG OPERATOR_VERSION)
	docker build --build-arg VERSION=$(OPERATOR_VERSION) -t "${IMG}:${OPERATOR_TAG}" -f $(CURDIR)/packaging/operator.Dockerfile .
	docker tag "${IMG}:${OPERATOR_TAG}" "${IMG}:latest-csi-operator"

operator-push: ## Push operator docker image to docker repository (specified in defaults)
	@$(call check_required_env,IMG OPERATOR_TAG)
	docker push "${IMG}:${OPERATOR_TAG}"
	docker push "${IMG}:latest-csi-operator"

######################
# CSI OPERATOR BUNDLE
######################
operator-bundle-gen: ## Generate bundle manifests and metadata, then validate generated files (NOTE: for prod builds IMG_PULL_SECRET and PIPE should be null).
	@$(call check_required_env,IMG CSI_PLUGIN_IMG OPERATOR_TAG CSI_TAG EXTENSIONS_TAG CHANNEL)
	@$(call check_non_required_env,IMG_PULL_SECRET PIPE EXTENSIONS_IMG)
	@$(CURDIR)/packaging/gen-operator-bundle.sh $(CURDIR) $(CHANNEL) \
          --set olmBuild=$${USE_OLM:-true} \
          --set installSnapshotCRDS=false \
          --set maturity=$(CHANNEL) \
          --set managerImage="$(shell scripts/concat_img_tag.sh $(IMG) $(OPERATOR_TAG))" \
          --set proxyImage=$${OPERATOR_PROXY_IMG:-"docker.io/kubebuilder/kube-rbac-proxy@sha256:a2523c532c0c3d51a5396a901d7ded23e402a9a1492c783aae27af6d0c1d2ec5"} \
          --set overrides.csiVastPlugin.repository="$(shell scripts/concat_img_tag.sh $(CSI_PLUGIN_IMG) $(CSI_TAG))" \
          --set overrides.vastExtensionController.repository="$(shell scripts/concat_img_tag.sh $(EXTENSIONS_IMG) $(EXTENSIONS_TAG))" \
          --set imagePullSecret=$(IMG_PULL_SECRET) \
		  --set ciPipe=$(PIPE)
	@operator-sdk bundle validate $(CURDIR)/bundle

operator-bundle-build: ## Generate manifests, metadata etc and build docker bundle image
	@$(MAKE) operator-bundle-gen
	@$(call check_required_env,IMG OPERATOR_BUNDLE_TAG OPERATOR_VERSION CHANNEL)
	docker build --build-arg CHANNEL=${CHANNEL} -t "$(shell scripts/concat_img_tag.sh $(IMG) $(OPERATOR_BUNDLE_TAG))" -f $(CURDIR)/packaging/operator_bundle.Dockerfile .
	docker tag "$(shell scripts/concat_img_tag.sh $(IMG) $(OPERATOR_BUNDLE_TAG))" "${IMG}:latest-csi-operator-bundle"

operator-bundle-push: ## Push bundle image to docker repository (specified in defaults)
	@$(call check_required_env,IMG OPERATOR_BUNDLE_TAG)
	docker push "${IMG}:${OPERATOR_BUNDLE_TAG}"
	docker push "${IMG}:latest-csi-operator-bundle"

# Lint the generated local bundle directory with the CI yamllint rules
# Usage: make operator-bundle-lint (expects ./bundle to exist)
operator-bundle-lint: ## Lint ./bundle YAMLs using yamllint with CI rule-set (line-length is warning)
	@if [ ! -d "$(CURDIR)/bundle" ]; then \
		echo "Bundle directory 'bundle' not found. Run 'make operator-bundle-build' first."; \
		exit 1; \
	fi; \
	echo "Linting YAMLs in ./bundle"; \
	yamllint "$(CURDIR)/bundle" -d '{extends: default, rules: {line-length: {max: 180, level: warning}, indentation: {indent-sequences: whatever}}}'

# Helper to remove trailing spaces (fixes yamllint trailing-spaces errors) from ./bundle
# Usage: make operator-bundle-fix-trailing-spaces (expects ./bundle to exist)
operator-bundle-fix-trailing-spaces: ## Strip trailing spaces in ./bundle YAMLs (fix yamllint errors)
	@if [ ! -d "$(CURDIR)/bundle" ]; then \
		echo "Bundle directory 'bundle' not found. Run 'make operator-bundle-build' first."; \
		exit 1; \
	fi; \
	find "$(CURDIR)/bundle" -type f -name '*.yaml' -exec sed -i 's/[[:space:]]\+$$//' {} +; \
	echo "Removed trailing spaces in ./bundle"

######################
# OPENSHIFT HELPERS
######################
create-secret: create-csi-namespace ## Create secret for pulling images from the configured Docker registry
	@$(call check_required_env,NAMESPACE IMG_PULL_SECRET)
	kubectl create secret docker-registry --dry-run=client $(IMG_PULL_SECRET) \
	  --docker-server=$(DOCKER_REGISTRY) \
	  --docker-username=AWS \
	  --docker-password=$$(aws ecr get-login-password) \
	  --namespace=${NAMESPACE} -o yaml | kubectl apply -f -;

operator-bundle-run: create-secret ## Deploy bundle against the configured Kubernetes cluster in ~/.kube/config (auto-refreshes ECR credentials)
	@$(call check_required_env,IMG OPERATOR_BUNDLE_TAG NAMESPACE IMG_PULL_SECRET)
	@echo "ECR credentials refreshed, deploying operator bundle..."
	operator-sdk run bundle "${IMG}:${OPERATOR_BUNDLE_TAG}" --timeout 20m --namespace ${NAMESPACE} --install-mode OwnNamespace --pull-secret-name ${IMG_PULL_SECRET}

operator-bundle-upgrade-run: create-secret ##  Upgrade an Operator previously installed in the bundle format with OLM (auto-refreshes ECR credentials)
	@$(call check_required_env,IMG OPERATOR_BUNDLE_TAG NAMESPACE IMG_PULL_SECRET)
	@echo "ECR credentials refreshed, upgrading operator bundle..."
	operator-sdk run bundle-upgrade "${IMG}:${OPERATOR_BUNDLE_TAG}" --timeout 20m --namespace ${NAMESPACE} --pull-secret-name ${IMG_PULL_SECRET}

operator-bundle-clean: ## Cleanup bundle from the configured Kubernetes cluster in ~/.kube/config
	@$(call check_required_env,NAMESPACE)
	operator-sdk cleanup vast-csi-operator --namespace ${NAMESPACE}

######################
# DEVELOPMENT
######################

create-csi-namespace: ## Create namespace for CSI driver
	$(call check_required_env,NAMESPACE)
	@if ! kubectl get namespace $(NAMESPACE) > /dev/null 2>&1; then \
		echo "Namespace $(NAMESPACE) does not exist. Creating it..."; \
		kubectl create namespace $(NAMESPACE); \
	fi

create-csi-secret: create-csi-namespace ## Recreate secret for CSI driver
	@$(call check_required_env,ENDPOINT DEV_USERNAME DEV_PASSWORD)
	@echo "Recreating secret vast-mgmt in namespace $(NAMESPACE)..."; \
	kubectl delete secret vast-mgmt -n $(NAMESPACE) --ignore-not-found; \
	kubectl create secret generic vast-mgmt \
	  --from-literal=username='$(DEV_USERNAME)' \
	  --from-literal=password='$(DEV_PASSWORD)' \
	  --from-literal=endpoint='$(ENDPOINT)' \
	  -n $(NAMESPACE);


install-snapshost-crds: ## Install snapshot CRDs
	@$(CURDIR)/scripts/install_snapshot_crds.sh

install-cosi-crds: ## Install COSI CRDs and controller
	@$(CURDIR)/scripts/install_cosi_crds.sh

install-replication-crds: ## Install VolumeReplication CRDs and Operator (complete stack)
	@$(CURDIR)/scripts/install_replication_stack.sh

start-minikube: ## Start Minikube cluster
	@$(call check_required_env,MINIKUBE_DRIVER)
	@$(CURDIR)/scripts/start-minikube.sh

ifeq (run, $(firstword $(MAKECMDGOALS)))
  runargs := $(wordlist 2, $(words $(MAKECMDGOALS)), $(MAKECMDGOALS))
  $(foreach arg,$(runargs),$(eval $(arg):;@true))
endif

#   Run the CSI driver against a local cluster with the specified profile.
#
#   Usage:
#     make run <profile>
#
#   Arguments:
#     <profile>    - Required. Must be either 'nfs' or 'block'.
#
#   Environment Variables (required):
#     ENDPOINT           - VMS url or ip.
#     DEV_VIP_POOL      - VIP pool name for the storage class. (default is 'vippool-1')
#     DEV_VIEW_POLICY   - View policy to use in the driver. (default is 'default')
#     DEV_SUBSYSTEM     - Subsystem name (used by block profile). (default is 'vastcsi')
#     MINIKUBE_DRIVER   - Driver for Minikube (default is 'kvm2' for Linux and 'qemu2' for macOS).
#
#   Examples:
#     ENDPOINT=v95 make run nfs
#     ENDPOINT=v95 DEV_VIP_POOL=vippool-2 make run block
run: start-minikube create-csi-namespace install-snapshost-crds install-replication-crds create-csi-secret ## Run the CSI driver with a specified profile: 'nfs' or 'block'
	@$(call check_required_env,DEV_VIP_POOL DEV_VIEW_POLICY DEV_SUBSYSTEM)
	@profile="$(word 1, $(runargs))"; \
	if [ -z "$$profile" ]; then \
		echo "Missing profile argument. Usage: make run <nfs|block>"; \
		exit 1; \
	fi; \
	if [ "$$profile" != "nfs" ] && [ "$$profile" != "block" ]; then \
		echo "Invalid profile '$$profile'. Must be 'nfs' or 'block'."; \
		exit 1; \
	fi; \
	echo "✅  Running profile: $$profile"; \
	NAMESPACE=$(NAMESPACE) \
	VERSION=$${GIT_TAG:-local} \
	GIT_COMMIT=$${GIT_COMMIT:-local} \
	VIP_POOL=$(DEV_VIP_POOL) \
	VIEW_POLICY=$(DEV_VIEW_POLICY) \
	SUBSYSTEM=$(DEV_SUBSYSTEM) \
	skaffold dev -p "$$profile"


######################
# MISC
######################
docker-login-ecr: ## Login to AWS ECR
	aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin $(DOCKER_REGISTRY)

build_image: ## Build (and optionally push) Docker image to the configured Docker registry
	@$(call check_required_env,IMAGE_TAG DOCKERFILE)
	@$(call check_non_required_env,BASE_IMAGE_NAME PLATFORMS CACHE_FROM PUSH_ON_SUCCESS)
	@$(CURDIR)/packaging/build_image.sh

run_preflight: ## Run preflight checks for the operator Red Hat certification
	@$(call check_required_env,IMAGE_TAG PROJECT_ID)
	@$(CURDIR)/packaging/run_preflight.sh

run_csi_sanity: ## Run CSI sanity tests
	@$(call check_required_env,IMAGE_TAG)
	@$(CURDIR)/packaging/sanity.sh $(IMAGE_TAG)

compare_versions: ## Compare two sem versions
	@$(call check_required_env,CURRENT_DEFAULT_BRANCH NEW_DEFAULT_BRANCH)
	@$(CURDIR)/scripts/compare_versions.sh $(CURRENT_DEFAULT_BRANCH) $(NEW_DEFAULT_BRANCH)

help: ## Show help
	@echo "Please specify a build target. The choices are:"
	@awk -F ': ## ' '/^[a-zA-Z0-9_-]+:.* ## .*/ {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
