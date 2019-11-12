#!/bin/bash
export CSI_ENDPOINT=127.0.0.1:50051

mkdir /tmp/csi-volumes

python -m vast_csi.server &

csi-sanity --csi.endpoint=$CSI_ENDPOINT --ginkgo.failFast -ginkgo.progress -ginkgo.debug
