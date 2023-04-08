import pytest
from vast_csi.utils import is_ver_nfs4_present


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
