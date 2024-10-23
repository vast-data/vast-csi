import pytest
from vast_csi.utils import is_ver_nfs4_present, generate_ip_range


@pytest.mark.parametrize(
    "options, exepected",
    [
        ("vers=4,soft=true,noac", True),
        ("nfsvers=4,soft=true,noac", True),
        ("vers=4.1,soft=true,noac", True),
        ("vers=4.0,soft=true,noac", True),
        ("soft=true,vers=4.0,noac", True),
        ("soft=true,vers=4.0", True),
        ("", False),
        ("nfsverss=4,soft=true,noac", False),
        ("vers=3,soft=true,noac", False),
        ("avers=4,soft=true,noac", False),
        ("nfsvers=3.4,soft=true,noac", False),
        ("soft=true,vers=3,4noac", False),
        ("noac,vers= 4,noac", False),
        ("noac,vers = 4,noac", False),
    ]
)
def test_parse_nfs4_mount_option(options, exepected):
    """Test if nfsvers|vers=4 is parsed properly"""
    assert is_ver_nfs4_present(options) == exepected


@pytest.mark.parametrize("ip_ranges, expected", [
    (
            [["15.0.0.1", "15.0.0.4"], ["10.0.0.27", "10.0.0.30"]],
            ['15.0.0.1', '15.0.0.2', '15.0.0.3', '15.0.0.4', '10.0.0.27', '10.0.0.28', '10.0.0.29', '10.0.0.30']
    ),
    (
            [["15.0.0.1", "15.0.0.1"], ["10.0.0.20", "10.0.0.20"]],
            ['15.0.0.1', '10.0.0.20']
    ),
    ([], [])
])
def test_generate_ip_range(ip_ranges, expected):
    ips = generate_ip_range(ip_ranges)
    assert ips == expected
