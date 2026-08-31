from easypy.units import MINUTE
from lib.logging import logger

from lib.k8s._base import KubernetesResource
from lib.constants import CSI_NAMESPACE


class VastCSIDriver(KubernetesResource):
    resource_type = "vastcsidrivers"

    def create(self, builder, record_on_create=None):
        body = builder.result()
        self.namespace  = body.metadata.get("namespace", CSI_NAMESPACE)
        self.driver_type = body.spec.get("driverType", "nfs")
        self.apply([body])
        self.wait()
        return self._record_manifest(body, record_on_create=record_on_create)

    def wait(self, timeout: int = 5 * MINUTE):
        prefix = "block-vast" if getattr(self, "driver_type", "nfs") == "block" else "csi-vast"
        for suffix in ("controller", "node"):
            label = f"{prefix}-{suffix}"
            logger.info(f"Waiting for pod with label: app={label}")
            self.k8s.pods.wait(
                timeout=timeout,
                namespace=self.namespace,
                labels={"app": label},
                condition="Running",
                error_msg=f"Pod with label app={label} is not running",
            )
        logger.info(f"{prefix} controller and node pods are running")


class VastCluster(KubernetesResource):
    resource_type = "vastclusters"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)


class VastStorage(KubernetesResource):
    resource_type = "vaststorages"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)
