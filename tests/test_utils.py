import pytest
from vast_csi.utils import is_ver_nfs4_present, generate_ip_range, wrap_ipv6, string_to_static_uuid


@pytest.mark.parametrize(
    "options, exepected",
    [
        (["vers=4", "soft=true", "noac"], True),
        (["nfsvers=4", "soft=true", "noac"], True),
        (["vers=4.1", "soft=true", "noac"], True),
        (["vers=4.0", "soft=true", "noac"], True),
        (["soft=true", "vers=4.0", "noac"], True),
        (["soft=true", "vers=4.0"], True),
        ([], False),
        (["nfsverss=4", "soft=true", "noac"], False),
        (["vers=3", "soft=true", "noac"], False),
        (["avers=4", "soft=true", "noac"], False),
        (["nfsvers=3.4", "soft=true", "noac"], False),
        (["soft=true", "vers=3", "4noac"], False),
        (["noac", "vers= 4", "noac"], False),
        (["noac", "vers = 4", "noac"], False),
    ]
)
def test_parse_nfs4_mount_option(options, exepected):
    """Test if nfsvers|vers=4 is parsed properly"""
    assert is_ver_nfs4_present(options) == exepected


@pytest.mark.parametrize("ip_ranges, expected", [
    # IPv4 range test cases
    (
        [["15.0.0.1", "15.0.0.4"], ["10.0.0.27", "10.0.0.30"]],
        ['15.0.0.1', '15.0.0.2', '15.0.0.3', '15.0.0.4', '10.0.0.27', '10.0.0.28', '10.0.0.29', '10.0.0.30']
    ),
    (
        [["15.0.0.1", "15.0.0.1"], ["10.0.0.20", "10.0.0.20"]],
        ['15.0.0.1', '10.0.0.20']
    ),
    ([], []),
    # IPv6 range test cases
    (
        [["2001:db8::1", "2001:db8::4"]],
        ['2001:db8::1', '2001:db8::2', '2001:db8::3', '2001:db8::4']
    ),
    (
        [["::1", "::1"]],
        ['::1']
    ),
    (
        [["2001:db8::ff", "2001:db8::102"]],
        ['2001:db8::ff', '2001:db8::100', '2001:db8::101', '2001:db8::102']
    ),
    (
        [["2001:db8::a", "2001:db8::c"], ["fd00::1", "fd00::2"]],
        ['2001:db8::a', '2001:db8::b', '2001:db8::c', 'fd00::1', 'fd00::2']
    )
])
def test_generate_ip_range(ip_ranges, expected):
    ips = generate_ip_range(ip_ranges)
    assert ips == expected


@pytest.mark.parametrize(
    "addr, expected",
    [
        ("192.168.1.1", "192.168.1.1"),
        ("2001:db8::1", "[2001:db8::1]"),
        ("example.com", "example.com"),
        ("::", "[::]"),
        ("[2001:db8::1]", "[2001:db8::1]"),
        ("[::]", "[::]"),
        ("::1", "[::1]"),
        ("::ffff:192.168.1.1", "[::ffff:192.168.1.1]"),
        ("0:0:0:0:0:0:0:1", "[0:0:0:0:0:0:0:1]"),
        ("", ""),
        ("   ", "   "),
        ("[invalid::addr]", "[invalid::addr]"),
        ("2001:0db8:0000:0000:0000:ff00:0042:8329", "[2001:0db8:0000:0000:0000:ff00:0042:8329]"),
        ("example.com:8080", "example.com:8080"),
        ("192.168.1.1:2049", "192.168.1.1:2049"),
        ("[2001:db8::1]:2049", "[2001:db8::1]:2049"),
        ("2001:db8::1:2049", "[2001:db8::1:2049]"),
    ]
)
def test_wrap_ipv6(addr, expected):
    """Test if IPv6 address is wrapped in brackets"""
    assert wrap_ipv6(addr) == expected


@pytest.mark.parametrize("input_value, expected", [
    ("nqn.2023-01.io.vast:tenant1", "afa6c1de-cf88-5e9c-9ae9-9be476f926a3"),
    ("tenant2", "df01a830-f608-522a-9295-6d867e40f370"),
    ("example-volume", "c7b9d154-7fac-53bf-b33c-439817cad04e"),
])
def test_string_to_static_uuid_is_deterministic(input_value, expected):
    """Ensure UUID is deterministic and correctly computed."""
    assert string_to_static_uuid(input_value) == expected
