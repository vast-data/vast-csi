# Copyright 2015 gRPC authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""The Python implementation of the GRPC helloworld.Greeter server."""

from concurrent import futures
from functools import wraps
import logging
import inspect
import grpc

from . import csi_pb2_grpc
from .csi_pb2_grpc import ControllerServicer, NodeServicer, IdentityServicer
from . import csi_types as types


class Instrumented():

    def logged(func):

        rpc = func.__name__

        @wraps(func)
        def wrapper(self, request, context):
            peer = context.peer()
            params = {k: getattr(request, k) for k in dir(request) if not k.startswith("_")}
            logging.info(f"{peer} >>> {rpc}: {request}: {params}")
            try:
                ret = func(self, request=request, context=context)
            except Exception as exc:
                logging.exception(f"Exception during {rpc}: {type(exc)}")
                raise
            logging.info(f"{peer} <<< {rpc}: {ret!r}")
            return ret
        return wrapper

    @classmethod
    def __init_subclass__(cls):
        for name, _ in inspect.getmembers(cls.__base__, inspect.isfunction):
            if name.startswith("_"):
                continue
            func = getattr(cls, name)
            setattr(cls, name, cls.logged(func))
        super().__init_subclass__()


class Identity(IdentityServicer, Instrumented):

    def __init__(self):
        self.capabilities = []

    def GetPluginInfo(self, request, context):
        return types.InfoResp(
            name=CONF.plugin_name,
            vendor_version=CONF.plugin_version,
        )

    def GetPluginCapabilities(self, request, context):
        return types.CapabilitiesResp(
            capabilities=[
                types.Capability(service=types.Service(type=cap))
                for cap in self.capabilities])

    def Probe(self, request, context):
        if True:
            return types.ProbeRespOK
        else:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, 'something is wrong')


class Controller(ControllerServicer, Instrumented):

    def CreateVolume(self, request, context):
        pass


class Node(NodeServicer, Instrumented):
    pass


class CONF():
    plugin_version = "0.1.0"
    plugin_name = "com.vast.csi.plugin"

    controller = False
    node = True

    nfs_server_ip = "1.2.3.4"
    root_export = "/k8s"


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

    identity = Identity()
    csi_pb2_grpc.add_IdentityServicer_to_server(identity, server)

    if CONF.controller:
        identity.capabilities.append(types.ServiceType.CONTROLLER_SERVICE)
        csi_pb2_grpc.add_ControllerServicer_to_server(Controller(), server)

    if CONF.node:
        csi_pb2_grpc.add_NodeServicer_to_server(Node(), server)

    server.add_insecure_port('[::]:50051')
    server.start()

    logging.info("Server Started")
    server.wait_for_termination()


if __name__ == '__main__':
    logging.basicConfig(level=0, format="{asctime}|{levelname:7}|{thread:X}: {message}", style="{")
    serve()
