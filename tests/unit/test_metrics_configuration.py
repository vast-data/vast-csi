from lib.builders.helm.block import VastBlockHelmValuesBuilder
from lib.builders.helm.cosi import VastCosiHelmValuesBuilder
from lib.builders.helm.csi import VastCsiHelmValuesBuilder
from lib.builders.helm.fleet import FleetHelmValuesBuilder
from vast_csi.configuration import Config


def test_plugin_metrics_are_disabled_by_default(monkeypatch):
    monkeypatch.delenv("X_CSI_METRICS_ENABLED", raising=False)

    assert Config().metrics_enabled is False


def test_e2e_fleet_enables_metrics_for_csi_controller_and_node():
    fleet = FleetHelmValuesBuilder(
        csi=VastCsiHelmValuesBuilder.new(),
        block=VastBlockHelmValuesBuilder.new(),
        cosi=VastCosiHelmValuesBuilder.new(),
    ).with_csi_metrics()

    values = fleet.result_by_chart()
    for chart in ("vastcsi", "vastblock"):
        assert values[chart]["controller"]["metrics"]["enabled"] is True
        assert values[chart]["node"]["metrics"]["enabled"] is True

    assert "controller" not in values["vastcosi"]
    assert "node" not in values["vastcosi"]


def test_e2e_fleet_can_disable_metrics():
    fleet = FleetHelmValuesBuilder(
        csi=VastCsiHelmValuesBuilder.new(),
        block=VastBlockHelmValuesBuilder.new(),
        cosi=VastCosiHelmValuesBuilder.new(),
    ).with_csi_metrics(False)

    values = fleet.result_by_chart()
    for chart in ("vastcsi", "vastblock"):
        assert values[chart]["controller"]["metrics"]["enabled"] is False
        assert values[chart]["node"]["metrics"]["enabled"] is False
