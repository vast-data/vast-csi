# Copyright 2024 VAST Data Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import os
import importlib
from concurrent import futures
import grpc

from .logging import logger, init_logging
from .utils import patch_traceback_format
from .configuration import Config
from . import metrics


#  Core CSI plugins
PLUGINS = {"nfs", "cosi", "block"}

# CSI-Addons
ADDONS = {
    "replication[nfs]",
    "replication[block]",
    "volumegroup[nfs]",
    "volumegroup[block]",
}

# Mapping of addon names to their module names
ADDON_MODULE_MAP = {
    "replication[nfs]": "replication",
    "replication[block]": "replication",
    "volumegroup[nfs]": "volumegroup",
    "volumegroup[block]": "volumegroup",
}


def serve(plugin: str = None, addons: str = ""):
    """
    Start the CSI server with a core plugin and/or CSI-Addons.

    Args:
        plugin: Core CSI plugin type: "nfs", "cosi", or "block"
        addons: Comma-separated list of CSI-Addons to enable.
                Examples:
                - "replication[block]"
                - "replication[block],volumegroup[block]"

    At least one of plugin or addons must be specified.
    """
    # Suppress gRPC fork warnings when using subprocess (known gRPC issue #24917)
    os.environ.setdefault('GRPC_ENABLE_FORK_SUPPORT', '0')

    # Parse and validate addons
    addon_list = []
    if addons:
        addon_list = [a.strip() for a in addons.split(",") if a.strip()]
        invalid_addons = set(addon_list) - ADDONS
        assert not invalid_addons, (
            f"Invalid addon(s): {', '.join(sorted(invalid_addons))}. "
            f"Valid addons are: {', '.join(sorted(ADDONS))}"
        )

    # Validate core plugin (if provided)
    if plugin:
        assert plugin in PLUGINS, (
            f"Invalid plugin type: {plugin}. "
            f"Valid plugins are: {', '.join(sorted(PLUGINS))}"
        )

    # Exactly one of plugin or addons must be specified
    assert bool(plugin) != bool(addon_list), (
        "Exactly one of --plugin or --addons must be specified (not both, not neither). "
        f"Received: plugin={plugin!r}, addons={addons!r}. "
        f"Valid plugins: {', '.join(sorted(PLUGINS))}. "
        f"Valid addons: {', '.join(sorted(ADDONS))}."
    )

    patch_traceback_format()
    CONF = Config()
    init_logging(level=CONF.log_level)
    logger.info("%s: %s (%s)", CONF.plugin_name, CONF.plugin_version, CONF.git_commit)

    if not CONF.ssl_verify:
        import urllib3

        urllib3.disable_warnings()

    if CONF.metrics_enabled:
        # Automatically enable xprt metrics only for NFS driver (plugin="csi")
        # Block driver doesn't use NFS so no xprt metrics needed
        collect_nfs_xprt = (plugin == "csi")
        metrics.start_metrics_server(
            port=CONF.metrics_port,
            is_node_service=CONF.has_running_node,
            collect_nfs_xprt=collect_nfs_xprt
        )

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=CONF.worker_threads)
    )


    plugin_base = "vast_csi.plugins"

    # Load and register core plugin (if provided)
    if plugin:
        plugin_module = importlib.import_module(f"{plugin_base}.{plugin}")
        plugin_module.serve(server, CONF)
        logger.info(f"Registered core plugin: {plugin}")

    # Load and register CSI-Addons
    for addon in addon_list:
        module_name = ADDON_MODULE_MAP[addon]
        addon_module = importlib.import_module(f"{plugin_base}.{module_name}")
        addon_module.serve(server, CONF, addon)
        logger.info(f"Registered addon: {addon}")

    server.add_insecure_port(CONF.endpoint)
    server.start()

    # Build log message
    components = []
    if plugin:
        components.append(f"plugin: {plugin}")
    if addon_list:
        components.append(f"addons: [{', '.join(addon_list)}]")

    logger.info(
        f"Server started as '{CONF.mode}', listening on {CONF.endpoint}, "
        f"spawned threads {CONF.worker_threads}, {', '.join(components)}"
    )
    server.wait_for_termination()
