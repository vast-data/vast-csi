"""
Script can be used to create missing views on existing PVs after migrating from CSI Driver 2.1.

There are 2 prerequisites to execute script:
    1. Python version >= 3.6 is required
    2. kubectl utility should be installed and prepared to works with appropriate k8s cluster
"""
import re
import sys
import json
import base64
import asyncio
from functools import partial
from typing import Optional, ClassVar
from argparse import ArgumentParser
import urllib.request
import urllib.parse
import ssl

context = ssl._create_unverified_context()

# Input and output markers.
# These markers are used to distinguish input commands and output text of these commands.
IN_ATTRS = 42, "in <<<"  # color & label
OUT_ATTRS = 42, "out >>>"  # color & label
INFO_ATTRS = 45, "info"  # color & label ( used for any auxiliary information )


def print_with_label(text: str, color: int, label: str, ):
    spc = 8 - len(label)
    label = label + ''.join(' ' for _ in range(spc)) if spc > 0 else label
    print(f'\x1b[1;{color}m  {label} \x1b[0m', text)


def is_ver_nfs4_present(mount_options: str) -> bool:
    """Check if vers=4 or nfsvers=4 mount option is present in `mount_options` string"""
    for opt in mount_options.split(","):
        name, sep, value = opt.partition("=")
        if name in ("vers", "nfsvers") and value.startswith("4"):
            return True
    return False


class UserError(Exception):
    pass


class RestSession:

    def __init__(self, *args, auth, base_url, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = base_url.rstrip("/")
        auth = base64.b64encode(bytes('{}:{}'.format(*auth), "utf8")).decode()
        self.headers = {
            "content-type": "application/json",
            "authorization": f"Basic {auth}"
        }

    def _request(self, method, url, data={}):
        if method == "get":
            url += '?' + urllib.parse.urlencode(data)
            data = None
        else:
            data = json.dumps(data).encode()
        req = urllib.request.Request(url, headers=self.headers, data=data)
        with urllib.request.urlopen(req, context=context) as resp:
            if resp.getcode() not in (200, 201):
                raise UserError(f"Error occurred while requesting url {url}, reason: {resp.reason}")
            return json.loads(resp.read().decode())

    def get_view_policy(self, policy_name):
        if not (res := self._request("get", f"{self.base_url}/viewpolicies", data=dict(name=policy_name))):
            raise UserError(f"Provided view policy: {policy_name!r} doesn't exist")
        return res[0]["id"]

    def get_quota_by_id(self, quota_id):
        return self._request("get", f"{self.base_url}/quotas/{quota_id}")

    def get_view_by_path(self, path):
        return self._request("get", f"{self.base_url}/views", dict(path=path))

    def create_view(self, path, policy_id, protocol):
        data = {
            "path": path,
            "create_dir": True,
            "protocols": [protocol],
            "policy_id": policy_id
        }
        self._request("post", f"{self.base_url}/views/", data)


class ExecutionFactory:
    """Wrapper around SubprocessProtocol that allows to communicate with subprocess and store subprocess stdout."""

    VERBOSE: ClassVar[bool] = True  # Show full command output.

    def __init__(self, executor: "SubprocessProtocol"):
        self.executor = executor
        self.executor.factory = self
        self.stdout = ""

    def __call__(self, base_command: Optional[str] = ""):
        self.base_command = base_command
        return self.executor

    async def exec(self, command: str, keep_output: Optional[bool] = False) -> str:
        """
        Execute command. If 'base_command were provided during instantiation then final command is combination of
        base_command + command.
        Args:
            command: command to execute
            keep_output: flag indicates that command output must be suppressed (if True). Only stdout
                will be suppressed in this case.
        Returns:
            Combined output (stdout + stderr) after process is terminated.
        """
        command = f"{self.base_command} {command}".strip()

        if self.VERBOSE:
            color, label = IN_ATTRS
            # Print input command
            print_with_label(color=color, label=label, text=command)

        loop = asyncio.get_event_loop()
        transport, prot = await loop.subprocess_shell(partial(self.executor, keep_output=keep_output), command)
        # Wait process to complete.
        await prot.wait()
        transport.close()
        return self.stdout.strip()


@ExecutionFactory
class SubprocessProtocol(asyncio.SubprocessProtocol):

    def __init__(self, keep_output: Optional[bool] = False):
        """
        Args:
            keep_output: Show command output only if this flag is False.
        """
        super().__init__()
        self.exit_sentinel = asyncio.Event()
        self._factory_instance = self.factory
        self._factory_instance.stdout = ""
        self.keep_output = keep_output

    @classmethod
    async def exec(cls, command: str, keep_output: Optional[bool] = False) -> str:
        """
        Execute command in subprocess.
        If you initialized executor with 'base_command' prefix make sure you provided only sub part of command.
        Args:
            command: command to execute
            keep_output: flag indicates that command output must be suppressed (if True). Only stdout
                will be suppressed in this case.
        Returns:
            Combined output (stdout + stderr) after process is terminated.
        """
        return await cls.factory.exec(command=command, keep_output=keep_output)

    async def wait(self):
        """Wait command is completed."""
        await self.exit_sentinel.wait()

    def pipe_data_received(self, fd: int, data: bytes):
        """
        Called when the subprocess writes data into stdout/stderr pipe
        Args:
            fd: Integer file descriptor. 1 - stdout; 2 - stderr
            data: Received byte data.
        """
        verbose = self._factory_instance.VERBOSE
        color, label = OUT_ATTRS
        text = data.decode("utf-8")
        self._factory_instance.stdout += text

        if int(fd) == 2 and self.keep_output:
            # Use red color if file descriptor is stderr in order to highlight errors.
            text = f"\x1b[1;30;31m{text.strip()} \x1b[0m"
            # Show full output in case of error. Do not suppress stderr output in order to have full visibility
            # of error.
            print_with_label(color=color, label=label, text=text)

        elif verbose:
            if self.keep_output:
                # Show command output
                print_with_label(color=color, label=label, text=text)

            else:
                # If flag 'keep_output' is True show '...' instead full stdout data.
                print_with_label(color=color, label=label, text="...")

    def process_exited(self):
        """Called when subprocess has exited."""
        self.exit_sentinel.set()


async def grab_required_params():
    """
    Interaction with user. Gathering required params values from command line arguments
    """
    color, label = INFO_ATTRS
    parser = ArgumentParser()

    parser.add_argument("--view-policy", default="default",
                        help="The name of the existing view policy that will be allocated to newly created views.")
    parser.add_argument("--verbose", help="Show commands output.", default=False, action='store_true')
    args = parser.parse_args()
    print_with_label(color=color, label=label, text=f"The user has chosen following parameters: {vars(args)}")
    return args


async def main() -> None:
    """Main script entrypoint"""
    color, label = INFO_ATTRS
    _print = partial(print_with_label, color=color, label=label)

    # Grab user inputs (root_export and vip_pool_name) from command line arguments.
    user_params = await grab_required_params()

    # Create base bash executor.
    verbose = user_params.verbose
    SubprocessProtocol.VERBOSE = verbose
    bash_ex = SubprocessProtocol()

    # Get kubectl system path.
    kubectl_path = await bash_ex.exec("which kubectl")
    if not kubectl_path:
        raise UserError("Unable to find 'kubectl' within system path. Make sure kubectl is installed.")

    # Prepare kubectl executor.
    kubectl_ex = SubprocessProtocol(base_command=kubectl_path)

    vers = await kubectl_ex.exec("version --client=true --output=yaml", verbose)
    if "clientVersion" not in vers:
        raise UserError("Something wrong with kubectl. Unable to get client version")

    namespaces = [
        ns["metadata"]["name"] for ns in json.loads(await kubectl_ex.exec(f"get ns -o json"))["items"]
    ]
    for namespace in namespaces:
        try:
            mgmt_secret = json.loads(await kubectl_ex.exec(f"get secret/csi-vast-mgmt -o json -n {namespace}", False))
            break
        except json.JSONDecodeError:
            pass
    else:
        _print(f"The CSI driver cannot be found in any of the available namespaces.")
        sys.exit(1)

    all_pvs = json.loads(await kubectl_ex.exec("get pv -o json", False))["items"]

    username = base64.b64decode(mgmt_secret["data"]["username"]).decode('utf-8')
    password = base64.b64decode(mgmt_secret["data"]["password"]).decode('utf-8')

    controller_info = json.loads(
        await kubectl_ex.exec(f"get pod csi-vast-controller-0 -n {namespace} -o json", False))
    controller_env = {
        env_pair["name"]: env_pair.get("value")
        for container in controller_info["spec"]["containers"]
        if container['name'] == 'csi-vast-plugin'
        for env_pair in container["env"]
    }

    session = RestSession(base_url=f'https://{controller_env["X_CSI_VMS_HOST"]}/api', auth=(username, password))
    policy_id = session.get_view_policy(user_params.view_policy)
    _seen = set()
    for pv in all_pvs:
        pv_name = pv['metadata']['name']
        if pv["metadata"]["annotations"].get("pv.kubernetes.io/provisioned-by", "") != "csi.vastdata.com":
            continue
        quota_id = pv['spec']['csi']['volumeAttributes'].get("quota_id")
        if not quota_id:
            _print(f"PV {pv_name!r} is missing an expected 'quota_id' attribute; please consult with VAST support")
            continue
        if quota_id not in _seen:
            _seen.add(quota_id)
            quota_path = session.get_quota_by_id(quota_id)["path"]
            if session.get_view_by_path(quota_path):
                _print(f"View {quota_path} already exists")
            else:
                mount_options = pv["spec"].get("mountOptions", [""])[0]
                mount_options = ",".join(re.sub(r"[\[\]]", "", mount_options).replace(",", " ").split())
                if is_ver_nfs4_present(mount_options):
                    protocol = "NFS4"
                else:
                    protocol = "NFS"
                session.create_view(quota_path, policy_id, protocol)
                _print(f"View {quota_path} has been created")

                # Mark that pvc has been migrated from v2.1 to v2.2 of csi driver
                await kubectl_ex.exec(f"annotate pv {pv_name} --overwrite=true csi.vastdata.com/migrated-from=2.1")


if __name__ == '__main__':

    if sys.version_info < (3, 6):
        print("Make sure you're running script using version of python>=3.6")
        sys.exit(1)

    loop = asyncio.get_event_loop()

    try:
        loop.run_until_complete(main())
    except UserError as e:
        print(e)
        sys.exit(1)
