#!/bin/bash

set -e

mkdir -p /mnt/csi-volumes
grep -v "MOCK_VAST" /etc/exports > /tmp/exports
echo "/mnt/csi-volumes *(rw,sync,no_root_squash,no_subtree_check)  # MOCK_VAST" >> /tmp/exports
cp /tmp/exports /etc/exports

service nfs restart
