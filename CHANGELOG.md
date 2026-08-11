# CHANGELOG

## Version 2.6.6
* Added `ReadOnlyMany` (ROX) access mode support for the block CSI driver
* Changed default node pod `priorityClass` to `system-node-critical` to ensure node workloads are not evicted under resource pressure (VCSI-358)
* Added `ReadWriteOncePod` access mode support (VCSI-464)
* Added `csi_node_nvme_controller_info` Prometheus metric exposing NVMe controller state and metadata (`controller`, `subsysnqn`, `hostnqn`, etc) for block driver node pods. Auto-enabled for the block driver, sourced from nvme-cli and sysfs (VCSI-388)
* Added mTLS support for NFS mounts via a new `mtls_manager` component, enabling mutual TLS credential handling for secure NFS transport
* NFS `xprtsec` (TLS/mTLS): for NFSv3, set `mountproto=tcp` in StorageClass `mountOptions`; omit `mountproto` for NFSv4.
* Added async volume replication support via the extensions operator. Introduces `VolumeReplication` and `VolumeGroupReplication` CRDs, an addons controller, and supporting Helm configuration for both NFS and block drivers
* Fixed an issue causing too many quotas in response (VCSI-380)
* Removed the `volume_id` label from metrics to prevent unbounded cardinality (VCSI-537)
* Fixed stage and unpublish failures when mounts encounter I/O errors. `realpath` is now tolerant of I/O errors while iterating over mounts (VCSI-446)
* `e2fsck` now runs outside the container namespace. Removed the `-f` flag from routine filesystem checks (VCSI-538)
* Added exponential backoff for VTask polling. Block volume map/unmap retries are now keyed by volume ID (VCSI-530)
* Added `forceLazyUmountOnTimeout` (`X_CSI_FORCE_LAZY_UMOUNT_ON_TIMEOUT`) option. When enabled, a timed-out umount operation is retried using `umount -l` (lazy unmount), allowing the filesystem to detach immediately while cleanup is deferred until all file descriptors are closed
* Block: enabled `passthru_err_log_enabled` during NVMe staging to improve error visibility
* Block: concurrent `NodePublishVolume` requests targeting the same mount path are now serialized
* Block: added integrity validation for XFS filesystems during staging
* Block: `ext_resize` now detects and recovers from dirty superblocks (for example, snapshots of live filesystems) before resizing. The `-f` flag has been removed from the standard staging path
* Block: mount operations now use the `-vvv` option to provide more detailed logging
* Block: volumes are now deleted without `force=True` by default. If the API returns "Volume is mapped to hosts", the operation is automatically retried with `force=True`
* Updated `csi-snapshotter` sidecar from v7.0.1 to v8.2.0
* Fixed an issue causing too many quotaS in response (VCSI-380)
* Increased default mount/umount timeout from 30s to 90s (`mountUmountTimeout` / `X_CSI_MOUNT_UMOUNT_TIMEOUT`) to reduce premature lazy unmounts under slow storage. Increased `xfs_db` superblock read timeout from 10s to 30s for XFS integrity checks during block volume staging

## Version 2.6.5
* Additional logging and timeout for mount/unmount operations (VCSI-343)
* Added `EXPAND_VOLUME` node capability and implemented `NodeExpandVolume` as a no-op for NFS filesystem volumes. (VCSI-345)
* Disabled NVMe controller timeout (`ctrl_loss_tmo=-1`) to prevent premature disconnection during temporary network issues. (VCSI-346)
* Added `resolveMountSymlinks` configuration option to enable symlink resolution when querying mount information. When enabled, mount paths containing symlinks (e.g., `/dev/disk/by-uuid/*`) are resolved to their canonical paths before comparison. (VCSI-367)
* Optimized mount info parsing by using `hostPid` and Python standard library instead of `chroot + cat` for reading `/proc/self/mountinfo`. This improves performance and prevents `DeadlineExceeded` timeouts during volume re-attachment operations. (VCSI-367)
* Fixed VMS API caching to prevent concurrent requests for token acquisition and cluster version retrieval, improving performance and reducing API load
* Added `cacheMaxAgeSeconds` configuration option to enable HTTP caching for VMS API requests via Cache-Control headers. When set to a value greater than 0, allows VMS to cache responses, useful for handling burst traffic patterns and reducing VMS load
* Added `disableUsageStats` configuration option to disable sending plugin usage statistics to VAST cluster. When set to true, the CSI driver will not report plugin usage metrics to VMS
* Added Prometheus metrics support for CSI controller with configurable metrics endpoint exposing CSI RPC operation metrics (`csi_plugin_operations_total`, `csi_plugin_operations_seconds`). Includes optional ServiceMonitor CRD support for Prometheus Operator integration (VCSI-342)
* Added Prometheus metrics support for CSI node with configurable metrics endpoint exposing CSI RPC operations, mount/umount operations, NVMe connect operations, and NFS transport statistics. Includes optional ServiceMonitor CRD support for Prometheus Operator integration (VCSI-342)

## Version 2.6.4
* Added `blockHostsAutoPrune` option to automatically remove unused VAST Host entries (NQNs), preventing host sprawl in dynamic Kubernetes environments (VCSI-263)
* Added default performance optimization flags: `--perf-same_cpu_crypt`, `--perf-submit_from_crypt_cpus`, `--perf-no_read_workqueue`, `--perf-no_write_workqueue` for host encryption (VCSI-306)
* Updated default csi plugin container memory limit to 500Mi

## Version 2.6.3
* Added support for host encryption of volumes using LUKS for block CSI driver (VCSI-250). Thanks to Vishal Varma <vishal1.verma@intel.com> (Intel) for the contribution.
* Added support for `blockingClones` option in the StorageClass.
  When enabled, the CSI driver waits for the Global Snapshot Stream (GSS) to fully complete
  before returning from a volume clone operation. (VCSI-255)
* Added qosPolicy parameter for Block. Allow optional qos_policy_id storage class argument (unsupported via helm) (VCSI-267)
* Added tenant-scoped authentication capabilities to the VAST CSI driver, allowing users to authenticate as tenant administrators (VCSI-224)

## Version 2.6.2
* Added support for locating mount paths via symlinks.

## Version 2.6.1
* Added support for token-based authentication as an alternative to username and password (ORION-226852)

## Version 2.6.0
* Block CSI Driver (VCSI-193)

## Version 2.5.2
* Added support for IPv6 addresses when mounting volumes. IPv6 addresses are now automatically wrapped in square brackets.

## Version 2.5.1
* Custom driver name
* Allow optional qos_policy_id storage class argument (unsupported via helm) (VCSI-226)

## Version 2.5.0
* CSI driver operator (VCSI-173)
* Allow using VIPPool DNS name instead of the CSI choosing IPs (VCSI-167)
* Expose existing data via Static PV (VCSI-150)

## Version 2.4.3
* Support for multiple clusters via a single global secret

## Version 2.4.2
* Support for ARM architecture (VCSI-191)
* Bug Fix - do not expect VMS credentials in a non-ephemeral mounting flow (VCSI-196)

## Version 2.4.1
* Support for multiple Vast Clusters via using StorageClass secrets (VCSI-140) 
* Set a timeout on requests to VMS, to prevent worker threads hanging (VCSI-183)
* Improve mounting performance by support the use of VIPPool DNS, skipping an API call to the VMS (VCSI-167)
* Bug fix - allow using "tenant-less" VIP pools when running in client-based tenancy (VCSI-188)

## Version 2.4.0
* added Container Object Storage Interface (COSI) support (VCSI-159)
* added formal support for multitenancy via StorageClasses (VCSI-147)
* added support for mounting using fixed-ips instead of VIP pool (VCSI-170)
* added support for host mount options propagation via /etc/nfsmount.conf.d (VCSI-169)
* changed Controller pod to use 'Deployment' instead of 'Statefulset' (VCSI-166)

## Version 2.3.1
* added volume stats metrics on Node (VCSI-125)

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
