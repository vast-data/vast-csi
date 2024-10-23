.EXPORT_ALL_VARIABLES:
SHELL := /usr/bin/env bash
CURRENT_TARGET := $(firstword $(MAKECMDGOALS))

OPERATOR_VERSION := $(shell awk '/^version:/ { print $$2; exit }' $(CURDIR)/charts/vastcsi-operator/Chart.yaml | sed 's/"//g')
# Include content of .env file as environment for all make commands (if such file exists)
# For better usability you can create .env file and specify necessary variable here. For instance
# PIPE=12345
# ....
MAKEENV=/tmp/.csimakeenv
$(shell echo '' > ${MAKEENV} && chmod 777 ${MAKEENV})
IGNORE := $(shell [ -f .env ] && env `(cat .env | xargs)` | sed 's/=/:=/' | sed 's/^/export /' > ${MAKEENV})
include ${MAKEENV}

ifndef IMG
    IMG := $(DOCKER_REGISTRY)/dev/vast-csi
endif
ifndef CSI_PLUGIN_IMG
    CSI_PLUGIN_IMG := $(DOCKER_REGISTRY)/dev/vast-csi
endif
ifndef CHANNEL
CHANNEL := "alpha"
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
# OPERATOR_TAG=xxxxxx-operator
# OPERATOR_BUNDLE_TAG=xxxxxx-operator-bundle
# In more complex scenarios, you can specify all tags
# separately eg export CSI_TAG=vvvvvv OPERATOR_TAG=yyyyy-operator etc.
CSI_TAG := $(if $(CSI_TAG),$(CSI_TAG),$(PIPE))
OPERATOR_TAG := $(if $(OPERATOR_TAG),$(OPERATOR_TAG),$(if $(PIPE),$(PIPE)-operator))
OPERATOR_BUNDLE_TAG := $(if $(OPERATOR_BUNDLE_TAG),$(OPERATOR_BUNDLE_TAG),$(if $(PIPE),$(PIPE)-operator-bundle))
# Define the script for checking required environment variables
define check_required_env =
    printf "\033[32m[%s]\033[0m\n" $$CURRENT_TARGET
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
	@$(call check_required_env,IMG CSI_PLUGIN_IMG OPERATOR_TAG CSI_TAG CHANNEL)
	@$(call check_non_required_env,IMG_PULL_SECRET PIPE)
	@$(CURDIR)/packaging/gen-operator-bundle.sh $(CURDIR) $(CHANNEL) \
          --set olmBuild=true \
          --set installSnapshotCRDS=false \
          --set maturity=$(CHANNEL) \
          --set managerImage="${IMG}:${OPERATOR_TAG}" \
          --set overrides.csiVastPlugin.repository=$(CSI_PLUGIN_IMG):$(CSI_TAG) \
          --set imagePullSecret=$(IMG_PULL_SECRET) \
		  --set ciPipe=$(PIPE)
	@operator-sdk bundle validate $(CURDIR)/bundle

operator-bundle-build: ## Generate manifests, metadata etc and build docker bundle image
	@$(MAKE) operator-bundle-gen
	@$(call check_required_env,IMG OPERATOR_BUNDLE_TAG OPERATOR_VERSION CHANNEL)
	docker build --build-arg CHANNEL=${CHANNEL} -t "${IMG}:${OPERATOR_BUNDLE_TAG}" -f $(CURDIR)/packaging/operator_bundle.Dockerfile .
	docker tag "${IMG}:${OPERATOR_BUNDLE_TAG}" "${IMG}:latest-csi-operator-bundle"

operator-bundle-push: ## Push bundle image to docker repository (specified in defaults)
	@$(call check_required_env,IMG OPERATOR_BUNDLE_TAG)
	docker push "${IMG}:${OPERATOR_BUNDLE_TAG}"
	docker push "${IMG}:latest-csi-operator-bundle"

######################
# OPENSHIFT HELPERS
######################
create-secret: ## Create secret for pulling images from the configured Docker registry
	@$(call check_required_env,NAMESPACE IMG_PULL_SECRET)
	@if ! oc get namespace $(NAMESPACE) > /dev/null 2>&1; then \
		echo "Namespace $(NAMESPACE) does not exist. Creating it..."; \
		oc create namespace $(NAMESPACE); \
	fi
	oc create secret docker-registry --dry-run=client $(IMG_PULL_SECRET) \
	  --docker-server=$(DOCKER_REGISTRY) \
	  --docker-username=AWS \
	  --docker-password=$$(aws ecr get-login-password) \
	  --namespace=${NAMESPACE} -o yaml | oc apply -f -;

operator-bundle-run: ## Deploy bundle against the configured Kubernetes cluster in ~/.kube/config
	@$(call check_required_env,IMG OPERATOR_BUNDLE_TAG NAMESPACE IMG_PULL_SECRET)
	@if ! oc get secret "${IMG_PULL_SECRET}" -n "${NAMESPACE}" > /dev/null 2>&1; then \
		echo "${IMG_PULL_SECRET} secret does not exist in namespace ${NAMESPACE}. Run 'make create-secret' target first."; \
		exit 1; \
	fi
	operator-sdk run bundle "${IMG}:${OPERATOR_BUNDLE_TAG}" --timeout 10m --namespace ${NAMESPACE} --install-mode OwnNamespace --pull-secret-name ${IMG_PULL_SECRET}

operator-bundle-upgrade-run: ##  Upgrade an Operator previously installed in the bundle format with OLM
	@$(call check_required_env,IMG OPERATOR_BUNDLE_TAG NAMESPACE IMG_PULL_SECRET)
	@if ! oc get secret "${IMG_PULL_SECRET}" -n "${NAMESPACE}" > /dev/null 2>&1; then \
		echo "${IMG_PULL_SECRET} secret does not exist in namespace ${NAMESPACE}. Run 'make create-secret' target first."; \
		exit 1; \
	fi
	operator-sdk run bundle-upgrade "${IMG}:${OPERATOR_BUNDLE_TAG}" --timeout 10m --namespace ${NAMESPACE} --pull-secret-name ${IMG_PULL_SECRET}

operator-bundle-clean: ## Cleanup bundle from the configured Kubernetes cluster in ~/.kube/config
	@$(call check_required_env,NAMESPACE)
	operator-sdk cleanup vast-csi-operator --namespace ${NAMESPACE}

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

help: ## Show help
	@echo "Please specify a build target. The choices are:"
	@awk -F ': ## ' '/^[a-zA-Z0-9_-]+:.* ## .*/ {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
