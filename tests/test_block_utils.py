import json
from unittest.mock import patch, MagicMock
import pytest
from vast_csi.block_utils import hostcmd, get_connected_session

ver_2x_nvme_out = [
    {
        "HostNQN": "nqn.2014-08.org.nvmexpress:uuid:92772a1b-d036-4022-b441-1b0f972641c9",
        "HostID": "94300544-77e5-4544-a504-cf6778a60f5d",
        "Subsystems": [
            {
                "Name": "nvme-subsys1",
                "NQN": "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock",
                "IOPolicy": "round-robin",
                "Paths": [
                    {
                        "Name": "nvme1",
                        "Transport": "tcp",
                        "Address": "traddr=172.21.112.9,trsvcid=4420",
                        "State": "live",
                    },
                    {
                        "Name": "nvme1",
                        "Transport": "tcp",
                        "Address": "traddr=172.21.112.8,trsvcid=4420",
                        "State": "live",
                    },
                ],
            }
        ],
    }
]

ver_1x_nvme_out = {
    "Subsystems": [
        {
            "Name": "nvme-subsys0",
            "NQN": "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock",
            "Paths": [
                {
                    "Name": "nvme1",
                    "Transport": "tcp",
                    "Address": "traddr=172.21.112.9,trsvcid=4420",
                    "State": "live",
                },
                {
                    "Name": "nvme1",
                    "Transport": "tcp",
                    "Address": "traddr=172.21.112.8,trsvcid=4420",
                    "State": "live",
                },
            ],
        }
    ]
}


@pytest.mark.host_only
@pytest.mark.parametrize("sub_sys_out", [ver_1x_nvme_out, ver_2x_nvme_out])
def test_get_connected_session(sub_sys_out):
    """
    Output of nvme list-subsys command is different for nvme v1.x and v2.x.
    Purpose of this test is to verify parsing consistency.
    """
    known_subsys_nqn = "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock"
    unknown_subsys_nqn = "nqn.2024-08.com.vastdata:898f9ee2-cc09-5130-b8e4-ede79286dcc6:default:subsystem-4"
    host_nqn = "nqn.2014-08.org.nvmexpress:uuid:92772a1b-d036-4022-b441-1b0f972641c9"

    with patch.object(hostcmd, "nvme", MagicMock(return_value=json.dumps(sub_sys_out))):
        session = get_connected_session(sybsystem_nqn=known_subsys_nqn, host_nqn=host_nqn)
        assert session
        session = get_connected_session(sybsystem_nqn=unknown_subsys_nqn, host_nqn=host_nqn)
        assert not session
