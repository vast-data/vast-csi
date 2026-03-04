#!/usr/bin/env bash

set -e

# Get the directory of the current script
SCRIPT_DIR=$(dirname "$(realpath "$0")")

source "${SCRIPT_DIR}/misc.sh"

PROFILE="vastcsi"
MINIKUBE_DRIVER="${MINIKUBE_DRIVER:-}" # MINIKUBE_DRIVER remains empty unless explicitly provided
NAMESPACE="${NAMESPACE:-default}"  # Default namespace


unset KUBECONFIG
# Function to check kubectl connectivity
check_kubectl_connection() {
  kubectl cluster-info > /dev/null 2>&1
  return $?
}

start_minikube() {
  log_info "🚀 Starting Minikube with driver '$MINIKUBE_DRIVER'..."
  minikube start \
    --driver="$MINIKUBE_DRIVER" \
    -p "$PROFILE"

  minikube config set driver "$MINIKUBE_DRIVER" -p "$PROFILE"
  minikube addons enable ingress -p "$PROFILE"
}

get_minikube_driver() {
  minikube config get driver -p "$PROFILE" 2>/dev/null || echo ""
}

# Check if Minikube is already running
if minikube status -p "$PROFILE" | grep -q "Running"; then
  CURRENT_DRIVER=$(get_minikube_driver)
  log_info "Minikube is already running with the profile '$PROFILE' using driver '$CURRENT_DRIVER'."

  # If DRIVER is explicitly set, and it differs from CURRENT_DRIVER, restart Minikube
  if [[ -n "$MINIKUBE_DRIVER" && "$CURRENT_DRIVER" != "$MINIKUBE_DRIVER" ]]; then
    log_warning "Driver mismatch: current driver is '$CURRENT_DRIVER', but the desired driver is '$MINIKUBE_DRIVER'. Restarting Minikube..."
    minikube delete -p "$PROFILE"
    start_minikube

    if [ $? -eq 0 ]; then
      log_info "Minikube restarted successfully with the profile '$PROFILE' and driver '$MINIKUBE_DRIVER'."
    else
      log_error "Failed to restart Minikube. Please check the logs."
    fi
  else
    log_info "No driver change needed. Minikube is running with the correct driver."
    if check_kubectl_connection; then
      kubectl config set-context --current --namespace="$NAMESPACE"
      log_info "Kubectl namespace set to '$NAMESPACE'."
    else
      log_warning "Kubectl cannot reach Minikube. Please check the cluster configuration."
    fi
  fi
else
  log_info "Minikube is not running. Determining the driver to use..."
  CURRENT_DRIVER=$(get_minikube_driver)
  minikube delete -p "$PROFILE" > /dev/null 2>&1

  # Determine which driver to use (default to docker if MINIKUBE_DRIVER is unset and no existing configuration)
  if [[ -z "$MINIKUBE_DRIVER" ]]; then
    if [[ -n "$CURRENT_DRIVER" ]]; then
      MINIKUBE_DRIVER="$CURRENT_DRIVER"
      log_info "Using previously configured driver '$'."
    else
      MINIKUBE_DRIVER="docker"
      log_info "No driver specified, defaulting to '$MINIKUBE_DRIVER'."
    fi
  fi

  start_minikube

  if [ $? -eq 0 ]; then
    log_info "Minikube started successfully with the profile '$PROFILE' and driver '$MINIKUBE_DRIVER'."
    if check_kubectl_connection; then
      kubectl config set-context --current --namespace="$NAMESPACE"
      log_info "Kubectl namespace set to '$NAMESPACE'."
    else
      log_error "Failed to connect to Minikube after starting it."
    fi
  else
    log_error "Failed to start Minikube. Please check the logs."
  fi
fi
