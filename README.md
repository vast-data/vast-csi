# VAST Data CSI Driver

The VAST Data CSI Driver allows Kubernetes clusters to dynamically provision persistent volumes on VAST Data storage systems.

## Overview

This driver implements the [Container Storage Interface (CSI)](https://github.com/container-storage-interface/spec) specification for container orchestrators like Kubernetes to manage the lifecycle of VAST Data storage.

### Key Features

- Dynamic volume provisioning (NFS and Block Storage)
- Snapshots and clones
- Volume resizing
- Ephemeral volumes
- Multi-tenancy support
- Container Object Storage Interface (COSI) support
- Quality of Service (QoS) policies
- Multiple VAST clusters support
- ARM architecture support

## Official Documentation

The source-code in this repository is for informational purposes only. It is not meant to be used directly.
If you wish to use our driver with your VAST storage system, please refer to our [official documentation](https://support.vastdata.com/s/topic/0TOV400000026yzOAA/vast-csi-driver).

## Support

Avoid opening issues within this project for support requests.
If you need support, please use VAST's Customer Support channels - https://support.vastdata.com
