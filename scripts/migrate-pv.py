"""
Migration process from csi driver==2.0 to csi driver==2.1
This script check if K8s cluster contains any PVs with storageClassName" == "vastdata-filesystem" and if
These PVs have all necessary parameters to works with driver 2.1.

There are 2 prerequisites to execute script:
    1. Python version >= 3.6 is required
    2. kubectl utility should be installed and prepared to works with appropriate k8s cluster

Usage:
    python migrate-pv.py --root_export < your input >  --vip_pool_name < your input >
"""
import sys
import json
import asyncio
from pathlib import Path
from functools import partial
from tempfile import gettempdir
from argparse import ArgumentParser, Namespace
from typing import Optional, Dict, Any, List

TMP = Path(gettempdir())

# Input and output markers.
# These markers are used to distinguish input commands and output text of these commands.
IN_ATTRS = 47, "in <<<"  # color & label
OUT_ATTRS = 42, "out >>>"  # color & label
INFO_ATTRS = 45, "info"  # color & label ( used for any auxiliary information )

# Filter criteria by storage class name.
# We should skip PersistentVolumes where storageClassName != vastdata-filesystem
STORAGE_CLASS_NAME = "vastdata-filesystem"

# These fields are required for csi driver 2.1 to work properly. If at least one parameter is missing it means
# PV must be updated.
REQUIRED_PARAMETERS = {"root_export", "vip_pool_name"}


def print_with_label(color: int, label: str, text: str):
    spc = 8 - len(label)
    label = label + ''.join(' ' for _ in range(spc)) if spc > 0 else label
    print(f'\x1b[1;{color}m  {label} \x1b[0m', text)


class UserError(Exception): ...


class ExecutionFactory:
    """Wrapper around SubprocessProtocol that allows to communicate with subprocess and store subprocess stdout."""

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
        color, label = IN_ATTRS
        command = f"{self.base_command} {command}".strip()
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
        color, label = OUT_ATTRS
        text = data.decode("utf-8")
        self._factory_instance.stdout += text

        if int(fd) == 2:
            # Use red color if file descriptor is stderr in order to highlight errors.
            text = f"\x1b[1;30;31m{text.strip()} \x1b[0m"
            # Show full output in case of error. Do not suppress stderr output in order to have full visibility
            # of error.
            print_with_label(color=color, label=label, text=text)

        elif not self.supress_output:
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

    parser.add_argument("--root_export", required=True, help="Base path where volumes will be located on VAST")
    parser.add_argument("--vip_pool_name", required=True, help="Name of VAST VIP pool to use")
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
    """
    color, label = INFO_ATTRS
    _print = partial(print_with_label, color=color, label=label)
    if candidates:

        # Convert 'root_export' key/value to 'root_export' key/value
        # as driver v2.1 uses 'root_export' param internally.
        user_params = {
            "root_export": user_params.root_export,
            "vip_pool_name": user_params.vip_pool_name
        }

        names = [c["metadata"]["name"] for c in candidates]
        _print(text=f"Found {len(names)} PV(s) to update:\nNames: {', '.join(names)}")

        for candidate in candidates:
            pv_name = candidate['metadata']['name']
            pv_manifest = TMP / f"{pv_name}.json"
            candidate["spec"]["csi"]["volumeAttributes"].update(user_params)

            with pv_manifest.open("w") as f:
                json.dump(candidate, f)

            # Add custom finalizer "vastdata.com/pv-migration-protection" in order to protect PV from being deleted
            # by csi driver at the moment of patching.
            await executor.exec(
                f"patch pv {pv_name} " +
                "-p '{\"metadata\":{\"finalizers\":[\"vastdata.com/pv-migration-protection\"]}}'")

            # Run task that remove all finalizers in the background.
            loop.create_task(patch_terminated_pv(pv_name=pv_name, executor=executor))

            # Replace original PV resource with patched version.
            await executor.exec(f"replace -f {pv_manifest} --force")
            _print(text=f"PV {pv_name} updated.")

    else:
        _print(text="No outdated PVs found.")
    _print(text="Done.")


async def main(loop: asyncio.AbstractEventLoop) -> None:
    """Main script entrypoint"""
    color, label = INFO_ATTRS
    _print = partial(print_with_label, color=color, label=label)

    # Grab user inputs (root_export and vip_pool_name) from command line arguments.
    user_params = await grab_required_params()

    # Create base bash executor.
    bash_ex = SubprocessProtocol()

    # Get kubectl system path.
    kubectl_path = await bash_ex.exec("which kubectl")
    if not kubectl_path:
        raise UserError("Unable to find 'kubectl' within system path. Make sure kubectl is installed.")

    # Prepare kubectl executor.
    kubectl_ex = SubprocessProtocol(base_command=kubectl_path)

    vers = await kubectl_ex.exec("version --client=true --output=yaml")
    if not "clientVersion" in vers:
        raise UserError("Something wrong with kubectl. Unable to get client version")

    all_pvs = await kubectl_ex.exec("get pv -o json", True)
    all_pvs = json.loads(all_pvs)["items"]

    candidates = []
    for pv in all_pvs:
        # Filter only PersistentVolumes where storageClassName == 'vastdata-filesystem'
        pv_spec = pv["spec"]
        if pv_spec["storageClassName"] == STORAGE_CLASS_NAME:
            volume_attributes = pv_spec["csi"]["volumeAttributes"]
            missing_params = REQUIRED_PARAMETERS.difference(volume_attributes)
            if missing_params:
                _print(text=f"PV {pv['metadata']['name']} will be patched {', '.join(missing_params)}")
                for missing_param in missing_params:
                    # Validate if missing_param were provided by user as command line argument. If not raise error.
                    if not getattr(user_params, missing_param):
                        raise UserError(f"{missing_param!r} is required."
                                         f" Use --{missing_param} < your input > while execution this script.")
                candidates.append(pv)

    # Start migration process
    await process_migrate(candidates=candidates, user_params=user_params, executor=kubectl_ex, loop=loop)


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
