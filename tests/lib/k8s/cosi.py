from lib.k8s._base import KubernetesResource


class BucketClass(KubernetesResource):
    """Cluster-scoped BucketClass."""

    resource_type = "bucketclass"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)

    def _namespace_from_manifest(self, manifest):
        return None


class BucketClaim(KubernetesResource):
    resource_type = "bucketclaim"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)


class BucketAccessClass(KubernetesResource):
    """Cluster-scoped BucketAccessClass."""

    resource_type = "bucketaccessclass"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)

    def _namespace_from_manifest(self, manifest):
        return None


class BucketAccess(KubernetesResource):
    resource_type = "bucketaccess"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)
