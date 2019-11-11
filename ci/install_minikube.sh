#!/bin/bash

set -e

if ! which kubectl; then
	VERSION=$(curl -s https://storage.googleapis.com/kubernetes-release/release/stable.txt)
	echo "Installing kubectl $VERSION"
	curl -LO https://storage.googleapis.com/kubernetes-release/release/$VERSION/bin/linux/amd64/kubectl
	chmod +x ./kubectl
	sudo mkdir -p /usr/local/bin/
	sudo install ./kubectl /usr/local/bin/
	kubectl version -oyaml

	yum install -y bash-completion
	grep -v "kubectl completion" ~/.bashrc > /tmp/bashrc
	echo "which kubectl >/dev/null && source <(kubectl completion bash) || true" >> /tmp/bashrc
	cp /tmp/bashrc ~/.bashrc
	rm /tmp/bashrc
fi

if ! which minikube; then
	echo "Installing minikube"
	curl -Lo minikube https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
	chmod +x minikube
	sudo install minikube /usr/bin/
	minikube version
fi

K8_VERSION=1.15.3
echo "Starting minikube cluster ($K8_VERSION)"
minikube start --kubernetes-version=$K8_VERSION
eval $(minikube docker-env)

kubectl -n kube-system create secret generic \
	csi-vast-mgmt \
	--from-literal=username=root \
	--from-literal=password='IamGroot!'
