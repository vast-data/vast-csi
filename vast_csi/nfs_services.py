"""Run NFS client services (rpcbind, rpc.statd, ...) in-container as a node sidecar.

Deployed on node OSes (e.g. VKS, NKP) that do not ship these services. The pod
runs with hostNetwork, so daemons started here are reachable by the host kernel
(e.g. lockd -> rpc.statd for NFSv3 locking). Each service is started only if the
host does not already provide it, so enabling the sidecar is safe anywhere.

Which daemons run is configurable via --services (default: statd,rpcbind).
Readiness differs per daemon: RPC-registered ones (rpcbind, statd, mountd) are
probed via rpcinfo; non-RPC ones (idmapd, tlshd) are considered ready once the
process survives a short settle.
"""

import argparse
import os
import signal
import subprocess
import time

from easypy.sync import wait, TimeoutException
from plumbum import local

from vast_csi.logging import logger

LOOPBACK = "127.0.0.1"
STATE_DIRS = ("/var/lib/nfs/sm", "/var/lib/nfs/sm.bak", "/run")
RPC_PIPEFS = "/var/lib/nfs/rpc_pipefs"
READY_TIMEOUT = 30  # seconds to wait for an RPC-registered daemon to register
POLL_INTERVAL = 0.5
SETTLE_SECONDS = 2  # a non-RPC daemon is "ready" if it stays alive this long


class NfsService:
    """A single NFS client daemon plus how to probe and launch it.

    rpc_program is the portmapper program name (for rpcinfo). It is None for
    daemons that do not register with rpcbind (idmapd via rpc_pipefs, tlshd via
    netlink), which cannot be discovered through the portmapper.
    """

    def __init__(self, name, argv, rpc_program=None, setup=None):
        self.name = name
        self.argv = argv
        self.rpc_program = rpc_program
        self.setup = setup  # optional pre-start hook (e.g. mount rpc_pipefs)

    def registered(self) -> bool:
        """True if the daemon's RPC program answers on the local portmapper.

        Always False for non-RPC daemons (idmapd/tlshd): they don't register
        with rpcbind, so use `running()` to detect them on the host instead.
        """
        if not self.rpc_program:
            return False
        retcode, _, _ = local["rpcinfo"][
            "-T", "udp", LOOPBACK, self.rpc_program
        ].run(retcode=None)
        return retcode == 0

    def running(self) -> bool:
        """True if the host already provides this daemon (skip self-starting it).

        RPC daemons are detected via the portmapper. Non-RPC daemons
        (idmapd/tlshd) are detected by scanning host processes -- the pod runs
        with hostPID, so a host-side daemon is visible in /proc and we must not
        start a duplicate (socket/keyring conflict).
        """
        if self.rpc_program:
            return self.registered()
        return _proc_running(os.path.basename(self.argv[0]))

    def start(self):
        logger.info("%s: starting (%s)", self.name, " ".join(self.argv))
        return local[self.argv[0]][self.argv[1:]].popen()


def _proc_running(comm: str) -> bool:
    """True if any live process has this comm name (matches /proc/<pid>/comm).

    The kernel truncates comm to TASK_COMM_LEN-1 (15) chars, so compare against
    the same truncation -- otherwise a daemon whose name exceeds 15 chars would
    never match and we'd spawn a duplicate (the conflict this guards against).
    """
    comm = comm[:15]
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm") as f:
                if f.read().strip() == comm:
                    return True
        except OSError:
            continue  # process gone or unreadable
    return False


def _ensure_idmapd_prereqs() -> None:
    """rpc.idmapd talks to the kernel via rpc_pipefs; mount it if absent."""
    os.makedirs(RPC_PIPEFS, exist_ok=True)
    retcode, _, _ = local["mountpoint"]["-q", RPC_PIPEFS].run(retcode=None)
    if retcode != 0:
        logger.info("idmapd: mounting rpc_pipefs at %s", RPC_PIPEFS)
        local["mount"]["-t", "rpc_pipefs", "sunrpc", RPC_PIPEFS].run(retcode=None)


# Ordered by dependency: rpcbind first (statd/mountd register with it).
SERVICE_REGISTRY = {
    "rpcbind": NfsService("rpcbind", ["rpcbind", "-w", "-f"], rpc_program="portmapper"),
    "statd": NfsService("statd", ["rpc.statd", "-F"], rpc_program="status"),
    "idmapd": NfsService("idmapd", ["rpc.idmapd", "-f"], setup=_ensure_idmapd_prereqs),
    "mountd": NfsService("mountd", ["rpc.mountd", "-F"], rpc_program="mountd"),
    "tlshd": NfsService("tlshd", ["tlshd"]),
}

DEFAULT_SERVICES = ("statd", "rpcbind")


def parse_services(raw: str) -> list:
    """Parse the comma-separated --services value; default to statd,rpcbind."""
    if not raw or not raw.strip():
        names = DEFAULT_SERVICES
    else:
        names = [part.strip().lower() for part in raw.split(",") if part.strip()]
    for name in names:
        if name not in SERVICE_REGISTRY:
            raise argparse.ArgumentTypeError(
                f"unknown nfs service: {name!r} "
                f"(valid: {', '.join(SERVICE_REGISTRY)})"
            )
    # Preserve dependency order regardless of input order.
    return [name for name in SERVICE_REGISTRY if name in set(names)]


def wait_registered(names, timeout: int = READY_TIMEOUT) -> bool:
    """Block until every RPC daemon in `names` is registered on the portmapper.

    Used by the CSI plugin as a mount preflight: the daemons run in a peer
    sidecar with no start-ordering guarantee, so before an NFSv3 mount we wait
    for locking (rpcbind/statd) to be up. Non-RPC daemons are ignored (nothing
    to probe). Returns True if all became registered within `timeout`, else
    False (caller decides whether to proceed).
    """
    services = [
        SERVICE_REGISTRY[n] for n in names
        if n in SERVICE_REGISTRY and SERVICE_REGISTRY[n].rpc_program
    ]
    if not services:
        return True
    try:
        wait(
            timeout,
            lambda: all(s.registered() for s in services),
            sleep=POLL_INTERVAL,
            message="waiting for NFS services: "
            + ", ".join(s.name for s in services),
        )
        return True
    except TimeoutException:
        return False


def _ensure_state_dirs() -> None:
    for path in STATE_DIRS:
        os.makedirs(path, exist_ok=True)


def _wait_ready(service: NfsService, proc) -> bool:
    if service.rpc_program:
        try:
            wait(
                READY_TIMEOUT,
                service.registered,
                sleep=POLL_INTERVAL,
                message=f"waiting for {service.name} to register",
            )
            return True
        except TimeoutException:
            return False
    # Non-RPC daemon: ready if it survives a short settle.
    wait(SETTLE_SECONDS)
    return proc.poll() is None


def _terminate(procs: list) -> None:
    for service, proc in procs:
        if proc.poll() is None:
            logger.info("%s: terminating", service.name)
            proc.terminate()
    for _, proc in procs:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _start_services(names) -> list:
    """Start each selected service the host does not already provide.

    Returns a list of (service, proc) for self-started daemons.
    Raises SystemExit if a started daemon fails to become ready in time.
    """
    _ensure_state_dirs()

    procs: list = []
    for name in names:
        service = SERVICE_REGISTRY[name]
        if service.running():
            logger.info("%s: already provided by host, skipping", name)
            continue
        if service.setup:
            service.setup()
        proc = service.start()
        procs.append((service, proc))
        if not _wait_ready(service, proc):
            _terminate(procs)
            timeout = READY_TIMEOUT if service.rpc_program else SETTLE_SECONDS
            raise SystemExit(f"{name}: failed to become ready within {timeout}s")
        logger.info("%s: ready", name)
    return procs


def _supervise(procs: list) -> None:
    """Block until a signal arrives or a self-started daemon dies.

    On SIGTERM/SIGINT: stop children and return (exit 0).
    On unexpected child exit: stop the rest and exit 1 so Kubernetes restarts us.
    """
    stopping = {"requested": False}

    def _handle_signal(signum, _frame):
        logger.info("received signal %s, stopping", signum)
        stopping["requested"] = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not stopping["requested"]:
        for service, proc in procs:
            retcode = proc.poll()
            if retcode is not None:
                _terminate(procs)
                raise SystemExit(f"{service.name}: exited with code {retcode}")
        time.sleep(POLL_INTERVAL)

    _terminate(procs)


def run_nfs_services(names) -> None:
    """Start missing NFS client services and supervise them until termination."""
    procs = _start_services(names)
    if not procs:
        logger.info("all selected NFS services already provided by host; idling")
    else:
        logger.info(
            "supervising: %s", ", ".join(service.name for service, _ in procs)
        )
    _supervise(procs)


def register_cli(subparsers) -> None:
    """Register the run-nfs-services CLI subcommand."""
    parser = subparsers.add_parser(
        "run-nfs-services",
        help="Run NFS client daemons in-container for NFS locking (node sidecar)",
    )
    parser.add_argument(
        "--services",
        type=parse_services,
        default=parse_services(""),
        help=(
            "Comma-separated daemons to run: "
            f"{', '.join(SERVICE_REGISTRY)} (default: {','.join(DEFAULT_SERVICES)})"
        ),
    )
    parser.set_defaults(func=run)


def run(args) -> None:
    """CLI entrypoint for the NFS client-services sidecar."""
    from vast_csi.configuration import Config
    from vast_csi.logging import init_logging

    init_logging(level=Config().log_level)
    run_nfs_services(args.services)
