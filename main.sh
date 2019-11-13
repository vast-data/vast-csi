#!/bin/bash

set -e


if [[ $1 == "sanity" ]]; then
	export CSI_ENDPOINT=${CSI_ENDPOINT:-127.0.0.1:50051}
	python -m vast_csi.server &
	csi-sanity \
		-csi.endpoint=$CSI_ENDPOINT \
		-ginkgo.failFast \
		-ginkgo.progress \
		-ginkgo.debug

else
	python -m vast_csi.server
fi
