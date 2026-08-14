from e2e.k8s._base import KubernetesResource


class BucketClaim(KubernetesResource):
    resource_type = "bucketclaim"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)


class BucketAccessClass(KubernetesResource):
    resource_type = "bucketaccessclass"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)


class BucketAccess(KubernetesResource):
    resource_type = "bucketaccess"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)
