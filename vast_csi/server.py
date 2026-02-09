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


def serve(plugin: str):
    assert plugin in {"csi", "cosi", "block"}, f"Invalid plugin type: {plugin}"

    # Suppress gRPC fork warnings when using subprocess (known gRPC issue #24917)
    os.environ.setdefault('GRPC_ENABLE_FORK_SUPPORT', '0')

    plugin_module = importlib.import_module(f"vast_csi.plugins.{plugin}")
    patch_traceback_format()
    CONF = Config()
    init_logging(level=CONF.log_level)
    logger.info("%s: %s (%s)", CONF.plugin_name, CONF.plugin_version, CONF.git_commit)

    if not CONF.ssl_verify:
        import urllib3

        urllib3.disable_warnings()

    if CONF.metrics_enabled:
        metrics.start_metrics_server(
            port=CONF.metrics_port,
            is_node_service=CONF.has_running_node
        )

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=CONF.worker_threads)
    )
    
    plugin_module.serve(server, CONF)
    server.add_insecure_port(CONF.endpoint)
    server.start()

    logger.info(f"Server started as '{CONF.mode}', listening on {CONF.endpoint}, spawned threads {CONF.worker_threads}")
    server.wait_for_termination()
