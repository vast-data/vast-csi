#!/usr/bin/env bash
set -euo pipefail

# Install CRDs
kubectl create -k github.com/kubernetes-sigs/container-object-storage-interface-api
# Install controller
kubectl create -k github.com/kubernetes-sigs/container-object-storage-interface-controller
