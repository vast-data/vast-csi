"""Composite builder that produces per-chart helm values for fleet setup."""
from __future__ import annotations

from typing import Any, Self

from e2e.builders.helm.block import VastBlockHelmValuesBuilder
from e2e.builders.helm.cosi import VastCosiHelmValuesBuilder
from e2e.builders.helm.csi import VastCsiHelmValuesBuilder


class FleetHelmValuesBuilder:
    """
    Builds helm ``subst_values`` for each VAST chart independently while sharing
    common settings (auth, image, pull secrets) across charts.
    """

    CHART_BUILDERS = {
        "vastcsi": VastCsiHelmValuesBuilder,
        "vastblock": VastBlockHelmValuesBuilder,
        "vastcosi": VastCosiHelmValuesBuilder,
    }

    def __init__(
        self,
        *,
        csi: VastCsiHelmValuesBuilder,
        block: VastBlockHelmValuesBuilder,
        cosi: VastCosiHelmValuesBuilder,
    ) -> None:
        self._csi = csi
        self._block = block
        self._cosi = cosi

    @classmethod
    def for_fleet(
        cls,
        system,
        *,
        csi_image: str | None = None,
        image_pull_secrets: tuple[str, ...] = (),
    ) -> Self:
        csi = VastCsiHelmValuesBuilder.for_fleet(system)
        block = VastBlockHelmValuesBuilder.for_fleet(system)
        cosi = VastCosiHelmValuesBuilder.for_fleet(system)

        builder = cls(csi=csi, block=block, cosi=cosi)
        if csi_image:
            repository, tag = csi_image.rsplit(":", 1)
            builder.with_image(repository, tag)
        if image_pull_secrets:
            builder.with_image_pull_secrets(*image_pull_secrets)
        return builder

    @property
    def csi(self) -> VastCsiHelmValuesBuilder:
        return self._csi

    @property
    def block(self) -> VastBlockHelmValuesBuilder:
        return self._block

    @property
    def cosi(self) -> VastCosiHelmValuesBuilder:
        return self._cosi

    def chart(self, name: str):
        try:
            return getattr(self, name.removeprefix("vast"))
        except AttributeError:
            raise KeyError(name) from None

    def with_image(self, repository: str, tag: str) -> Self:
        for chart_builder in (self._csi, self._block, self._cosi):
            chart_builder.with_image(repository, tag)
        return self

    def with_image_pull_secrets(self, *names: str) -> Self:
        for chart_builder in (self._csi, self._block, self._cosi):
            chart_builder.with_image_pull_secrets(*names)
        return self

    def result_by_chart(self) -> dict[str, dict[str, Any]]:
        return {
            "vastcsi": self._csi.result(),
            "vastblock": self._block.result(),
            "vastcosi": self._cosi.result(),
        }
