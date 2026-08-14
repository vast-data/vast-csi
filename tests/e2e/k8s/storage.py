from e2e.k8s._base import KubernetesResource


class PersistentVolumeClaim(KubernetesResource):
    resource_type = "pvc"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)


class PersistentVolume(KubernetesResource):
    resource_type = "pv"


class StorageClass(KubernetesResource):
    resource_type = "storageclass"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)


class VolumeSnapshot(KubernetesResource):
    resource_type = "volumesnapshot"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)


class VolumeSnapshotContent(KubernetesResource):
    resource_type = "volumesnapshotcontent"
