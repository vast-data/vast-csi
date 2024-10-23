"""
Migration process from csi driver==2.0 to csi driver==2.1
This script check if K8s cluster contains any PVs with storageClassName" == "vastdata-filesystem" and if
These PVs have all necessary parameters to works with driver 2.1.

There are 2 prerequisites to execute script:
    1. Python version >= 3.6 is required
    2. kubectl utility should be installed and prepared to works with appropriate k8s cluster

Usage:
    python migrate-pv.py --vast-csi-namespace < your input >  --verbose < True|False >
"""
import os
import sys
import json
import asyncio
from pathlib import Path
from functools import partial
from tempfile import gettempdir
from argparse import ArgumentParser, Namespace
from typing import Optional, Dict, Any, List, ClassVar

TMP = Path(gettempdir())

# Input and output markers.
# These markers are used to distinguish input commands and output text of these commands.
IN_ATTRS = 47, "in <<<"  # color & label
OUT_ATTRS = 42, "out >>>"  # color & label
INFO_ATTRS = 45, "info"  # color & label ( used for any auxiliary information )

# Filter criteria by storage class name.
# We should skip PersistentVolumes where
# "pv.kubernetes.io/provisioned-by" annotation is not equal to csi.vastdata.com
VAST_PROVISIONER = "csi.vastdata.com"
VAST_DRIVER_VERSION = "2.0"

# These fields are required for csi driver 2.1 to work properly. If at least one parameter is missing it means
# PV must be updated.
REQUIRED_PARAMETERS = {"root_export", "vip_pool_name"}


def print_with_label(color: int, label: str, text: str):
    spc = 8 - len(label)
    label = label + ''.join(' ' for _ in range(spc)) if spc > 0 else label
    print(f'\x1b[1;{color}m  {label} \x1b[0m', text)


class UserError(Exception):
    pass


class ExecutionFactory:
    """Wrapper around SubprocessProtocol that allows to communicate with subprocess and store subprocess stdout."""

    VERBOSE: ClassVar[bool] = True # Show full command output.

    def __init__(self, executor: "SubprocessProtocol"):
        self.executor = executor
        self.executor.factory = self
        self.stdout = ""

    def __call__(self, base_command: Optional[str] = ""):
        self.base_command = base_command
        return self.executor

    async def exec(self, command: str, supress_output: Optional[bool] = False) -> str:
        """
        Execute command. If 'base_command were provided during instantiation then final command is combination of
        base_command + command.
        Args:
            command: command to execute
            supress_output: flag indicates that command output must be suppressed (if True). Only stdout
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
        transport, prot = await loop.subprocess_shell(partial(self.executor, supress_output=supress_output), command)
        # Wait process to complete.
        await prot.wait()
        transport.close()
        return self.stdout.strip()


@ExecutionFactory
class SubprocessProtocol(asyncio.SubprocessProtocol):

    def __init__(self, supress_output: Optional[bool] = False):
        """
        Args:
            supress_output: Show command output only if this flag is False.
        """
        super().__init__()
        self.exit_sentinel = asyncio.Event()
        self._factory_instance = self.factory
        self._factory_instance.stdout = ""
        self.supress_output = supress_output

    @classmethod
    async def exec(cls, command: str, supress_output: Optional[bool] = False) -> str:
        """
        Execute command in subprocess.
        If you initialized executor with 'base_command' prefix make sure you provided only sub part of command.
        Args:
            command: command to execute
            supress_output: flag indicates that command output must be suppressed (if True). Only stdout
                will be suppressed in this case.
        Returns:
            Combined output (stdout + stderr) after process is terminated.
        """
        return await cls.factory.exec(command=command, supress_output=supress_output)

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

        if int(fd) == 2:
            # Use red color if file descriptor is stderr in order to highlight errors.
            text = f"\x1b[1;30;31m{text.strip()} \x1b[0m"
            # Show full output in case of error. Do not suppress stderr output in order to have full visibility
            # of error.
            print_with_label(color=color, label=label, text=text)

        elif verbose:
            if not self.supress_output:
                # Show command output
                print_with_label(color=color, label=label, text=text)

            else:
                # If flag 'supress_output' is True show '...' instead full stdout data.
                print_with_label(color=color, label=label, text="...")

    def process_exited(self):
        """Called when subprocess has exited."""
        self.exit_sentinel.set()


async def grab_required_params() -> Namespace:
    """
    Interaction with user. Gathering required params values from command line arguments
    """
    color, label = INFO_ATTRS
    parser = ArgumentParser()

    parser.add_argument("--vast-csi-namespace", default="vast-csi", help="Namespace where csi driver was deployed.")
    parser.add_argument("--verbose", help="Show commands output.", default=False)
    parser.add_argument("--root_export", help="Base path where volumes will be located on VAST")
    parser.add_argument("--vip_pool_name", help="Name of VAST VIP pool to use")
    parser.add_argument("--mount_options", help="Custom NFS mount options, comma-separated (specify '' for no mount options).", default="")
    parser.add_argument(
        "--force",
        help="Forced migration - refer to Vast Support documentation on when to use this flag",
        action='store_true')

    args = parser.parse_args()
    print_with_label(color=color, label=label, text=f"The user has chosen following parameters: {vars(args)}")
    return args


async def patch_terminated_pv(pv_name: str, executor: SubprocessProtocol) -> None:
    """Delete finalizers from provided PV where PV has 'Terminating' state."""
    while True:
        await asyncio.sleep(.5)
        if await executor.exec(f"get pv {pv_name} | grep Terminating"):
            await executor.exec(f"patch pv {pv_name} " + "-p '{\"metadata\":{\"finalizers\":null}}'")
            return


async def process_migrate(
        candidates: List[Dict[str, Any]],
        user_params: Namespace,
        executor: SubprocessProtocol,
        loop: asyncio.AbstractEventLoop) -> None:
    """
    Main migration process.
    1. Update manifest of candidate PV with missing params
    2. Write manifest to temporary file
    3. Remove all finalizers from PV
    4. replace PV resource on kubernetes from temporary file.
    5. Add annotation csi.vastdata.com/migrated-from=2.0
    """
    color, label = INFO_ATTRS
    _print = partial(print_with_label, color=color, label=label)

    if user_params.force:
        root_export = user_params.root_export
        vip_pool_name = user_params.vip_pool_name
        mount_options = user_params.mount_options

    else:
        csi_namespace = user_params.vast_csi_namespace
        controller_info = await executor.exec(f"get pod csi-vast-controller-0 -n {csi_namespace} -o json", True)
        try:
            controller_info = json.loads(controller_info)
        except json.decoder.JSONDecodeError:
            # In case of 'Error from server (NotFound) ...'
            raise UserError(f"Could not find our csi driver in namespace '{csi_namespace}'"
                            f" - please verify that the 'csi-vast-controller-0' is deployed in your cluster.\n"
                            f"If you've used a different namespace, specify it using the --vast-csi-namespace flag.")

        controller_env = {
            env_pair["name"]: env_pair.get("value")
            for container in controller_info["spec"]["containers"]
            if container['name'] == 'csi-vast-plugin'
            for env_pair in container["env"]
        }

        nodes_info = await executor.exec(f"get pod -l app=csi-vast-node -n {csi_namespace} -o json", True)
        try:
            nodes_info = json.loads(nodes_info)
            node_info = nodes_info['items'][0]
        except (json.decoder.JSONDecodeError, KeyError, IndexError):
            # In case of 'Error from server (NotFound) ...'
            raise UserError(f"Could not find our csi driver nodes in namespace '{csi_namespace}'.\n"
                            f"If you've used a different namespace, specify it using the --vast-csi-namespace flag.")

        node_env = {
            env_pair["name"]: env_pair.get("value")
            for container in node_info["spec"]["containers"]
            if container['name'] == 'csi-vast-plugin'
            for env_pair in container["env"]
        }

        root_export = controller_env.get("X_CSI_NFS_EXPORT")
        vip_pool_name = controller_env.get("X_CSI_VIP_POOL_NAME")
        mount_options = node_env.get("X_CSI_MOUNT_OPTIONS") or ""

        if not root_export or not vip_pool_name:
            raise UserError(
                "It looks like you've already upgraded your Vast CSI Driver - "
                "Please refer to Vast Support documentation on how to use this script in 'post-upgrade' mode.")

    patch_params = {
        "root_export": root_export,
        "vip_pool_name": vip_pool_name,
        "mount_options": mount_options,
        "schema": "2"
    }

    _print(text=f"Parameters for migration: {patch_params}")

    for candidate in candidates:
        pv_name = candidate['metadata']['name']
        pvc_name = candidate['spec'].get('claimRef', {}).get('name')
        pv_manifest = TMP / f"{pv_name}.json"

        patch_params['export_path'] = os.path.join(root_export, pv_name)
        candidate["spec"]["csi"]["volumeAttributes"].update(patch_params)
        if mount_options:
            candidate["spec"]["mountOptions"] = mount_options.split(",")

        with pv_manifest.open("w") as f:
            json.dump(candidate, f)

        # Add custom finalizer "vastdata.com/pv-migration-protection" in order to protect PV from being deleted
        # by csi driver at the moment of patching.
        await executor.exec(
            f"patch pv {pv_name} "
            "-p '{\"metadata\":{\"finalizers\":[\"vastdata.com/pv-migration-protection\"]}}'")

        # Run task that remove all finalizers in the background.
        loop.create_task(patch_terminated_pv(pv_name=pv_name, executor=executor))

        # Replace original PV resource with patched version.
        await executor.exec(f"replace -f {pv_manifest} --force")
        # Add new annotation to existing PV's annotations. Use --overwrite=true in case migration key already exist.
        await executor.exec(f"annotate pv {pv_name} --overwrite=true csi.vastdata.com/migrated-from=2.0")
        _print(text=f"PV {pv_name} updated.")

        if pvc_name:
            # Remove PVC events about "Lost" status
            await asyncio.sleep(5)
            pvc_events = await executor.exec(f'get events --field-selector involvedObject.name={pvc_name} -o json')
            pvc_events = json.loads(pvc_events)['items']

            for event in pvc_events:
                if 'Bound claim has lost its PersistentVolume' in event['message']:
                    event_name = event['metadata']['name']
                    await executor.exec(f'delete event {event_name}')


async def main(loop: asyncio.AbstractEventLoop) -> None:
    """Main script entrypoint"""
    color, label = INFO_ATTRS
    _print = partial(print_with_label, color=color, label=label)

    # Grab user inputs (root_export and vip_pool_name) from command line arguments.
    user_params = await grab_required_params()

    force_migrate = user_params.force

    if force_migrate and not all([
            user_params.root_export,
            user_params.vip_pool_name,
            user_params.mount_options is not None]):
        raise UserError(
            "--vip_pool_name, --root_export and --mount_options must be provided if you're using --force flag")

    # Set output verbosity
    SubprocessProtocol.VERBOSE = user_params.verbose

    # Create base bash executor.
    bash_ex = SubprocessProtocol()

    # Get kubectl system path.
    kubectl_path = await bash_ex.exec("which kubectl")
    if not kubectl_path:
        raise UserError("Unable to find 'kubectl' within system path. Make sure kubectl is installed.")

    # Prepare kubectl executor.
    kubectl_ex = SubprocessProtocol(base_command=kubectl_path)

    vers = await kubectl_ex.exec("version --client=true --output=yaml")
    if "clientVersion" not in vers:
        raise UserError("Something wrong with kubectl. Unable to get client version")

    all_pvs = await kubectl_ex.exec("get pv -o json", True)
    all_pvs = json.loads(all_pvs)["items"]

    candidates = []
    for pv in all_pvs:
        pv_annotations = pv["metadata"].get("annotations", {})

        if pv_annotations.get("pv.kubernetes.io/provisioned-by", "") != VAST_PROVISIONER:
            continue

        pv_spec = pv["spec"]
        volume_attributes = pv_spec["csi"]["volumeAttributes"]
        missing_params = REQUIRED_PARAMETERS.difference(volume_attributes)

        if pv_annotations.get("csi.vastdata.com/migrated-from") == VAST_DRIVER_VERSION and force_migrate:
            # Force migrate. Assumed previous parameters will be overwritten.
            _print(text=f"PV {pv['metadata']['name']} will be patched (re-migrating)")
            candidates.append(pv)

        elif missing_params:
            # Regular migrate. Assumed only PVs with missing required parameters will be updated.
            _print(text=f"PV {pv['metadata']['name']} will be patched {', '.join(missing_params)}")
            candidates.append(pv)

    # Start migration process
    if candidates:
        await process_migrate(candidates=candidates, user_params=user_params, executor=kubectl_ex, loop=loop)
    else:
        _print(text="No outdated PVs found.")


if __name__ == '__main__':

    if sys.version_info < (3, 6):
        print("Make sure you're running script using version of python>=3.6")
        sys.exit(1)

    loop = asyncio.get_event_loop()

    try:
        loop.run_until_complete(main(loop))
    except UserError as e:
        print(e)
        sys.exit(1)
