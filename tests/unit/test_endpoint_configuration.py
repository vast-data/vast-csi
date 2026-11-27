import pytest

from vast_csi.configuration import Config


@pytest.mark.parametrize(
    "configured, expected",
    [
        ("unix:///var/run/csi.sock", "unix:///var/run/csi.sock"),
        ("tcp://csi-controller:50051", "csi-controller:50051"),
        ("tcp://127.0.0.1:5000", "127.0.0.1:5000"),
        ("0.0.0.0:5000", "0.0.0.0:5000"),
        ("unix:///csi/csi.socket", "unix:///csi/csi.socket"),
    ],
)
def test_endpoint_removes_only_tcp_scheme(monkeypatch, configured, expected):
    monkeypatch.setenv("CSI_ENDPOINT", configured)

    assert Config().endpoint == expected
