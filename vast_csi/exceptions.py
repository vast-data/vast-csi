import grpc
from easypy.exceptions import TException


class Abort(Exception):
    @property
    def code(self):
        return self.args[0]

    @property
    def message(self):
        return self.args[1]


class ApiError(TException):
    template = "HTTP {response.status_code}: {response.text}"


class MissingParameter(Abort):
    def __init__(self, param: str):
        self.param = param

    @property
    def code(self):
        return grpc.StatusCode.INVALID_ARGUMENT

    @property
    def message(self):
        return (
            f"Parameter {self.param!r} cannot be empty string or None."
            f" Please provide a valid value for this parameter "
            f"in the parameters section of StorageClass"
        )


class MountFailed(TException):
    template = "Mounting {src} failed"
