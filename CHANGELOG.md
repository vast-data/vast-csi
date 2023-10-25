# CHANGELOG

## Version 2.3.0
* added CLONE_VOLUME support (VCSI-83)
* clone volumes from snapshots in READ_WRITE mode (VCSI-103)

## Version 2.2.6
* added `sslCertsSecretName` parameter, which points to a user-defined secret for the CSI driver to utilize for custom CA bundles. (VCSI-120)
* removed kubernetes version check (VCSI-130)
* advanced resources usage and pod allocation for csi node/controller (VCSI-131)
* when using Trash API for deletions, disallow removal of volume if it has snapshots, as a workaround for a Vast Storage temporary limitation (VCI-128)

## Version 2.2.5
* added adjustable timeout and number of workers (VCSI-100)
* added k8s error events and more informative error logging (VCSI-97)
* added multitenancy awareness (VCSI-114)
* removed password and username fields from values.yaml. Created new required field `secretName` (VCSI-115)
* added QoS policy support (VCSI-113)
* Misc
    * added `CHANGELOG.mg` (VCSI-95)

## Version 2.2.1 (05/16/23)
* added NFS4 support (inferred from mount options) (VCSI-78)
* created `create_views.py` script which creates missing views for PVCs provisioned by version 2.1 of CSI driver. (VCSI-86)
* Misc
    * updated helm release action version (VCSI-78)
    * renamed env variable `X_CSI_DISABLE_VMS_SSL_VERIFICATION` -> `X_CSI_ENABLE_VMS_SSL_VERIFICATION` (VCSI-81)
    * "volume_name", "view_policy" and "protocol" included in volume context for using on Node side (if needed) (VCSI-87)
 
## Version 2.2.0 (03/09/23)
* docker based csi template generator is replaces with helm chart. (VCSI-39)
* implemented view per volume feature (VCSI-38)
* added ssl certificates support. (VCSI-42)
* added `deletion_vip_pool` and `deletion_view_policy` parameters specifically for the purpose of performing a volume cleanse.
* Misc
    * added unit tests (VCSI-38)
    * exceptions were moved to `exception.py` (VCSI-38)
    * added intermediate base csi image. (VCSI-50)

## Version 2.1.2 (01/28/23)
* added NFS4 support (VCSI-68)
    
## Version 2.1.1 (12/29/22)
* trim the names to 64 characters (VCSI-68)
* Fix quota create volume when quota exists (VCSI-66)

## Version 2.1.0 (12/29/22)
* added `CREATE_DELETE_SNAPSHOT` and `LIST_SNAPSHOTS` Controller capabilities support (VCSI-15)
* added Ephemeral volumes support (VCSI-37)
* added `mount options` support (VCSI-56)
* added multiple StorageClass support. (VCSI-65)
* Misc
    * updated sidecar containers tags (VCSI-15)
    * all methods and classes related to communication with VMS moved to `vms_session.py` (VCSI-15)
    * all methods related to provisioning new volume/snapshot moved to `volume_builder.py` (VCSI-15)
    * Config class moved to `configuration.py` (VCSI-15)
    * created `migrate-pv.py` script to enhance PVCs provisioned by version 2.0 of the driver by adding necessary volume attributes (VCSI-44)
 
