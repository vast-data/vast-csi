FROM python:3.9-alpine

WORKDIR /root

RUN apk add --no-cache \
	# used by driver to mount
	nfs-utils \
	# used to compile grpcio
	linux-headers build-base && \
	pip install --no-cache-dir grpcio==1.25.0
