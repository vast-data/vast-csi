import grpc
from easypy.exceptions import TException
from easypy.sync import PredicateNotSatisfied


class Abort(Exception):
    @property
    def code(self):
        return self.args[0]

    @property
    def message(self):
        return self.args[1]


class ApiError(TException):
    template = "HTTP {response.status_code}: {response.text}"


class OperationNotSupported(TException):
    template = "Cluster does not support this operation - {op!r} (needs {required_version}, got {current_version})"


class LookupFieldError(TException):
    template = "Could not find {field}."


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


class UmountTimedOut(Exception):
    """Raised when umount command times out."""
    pass


class BuilderFailed(Exception):

    @property
    def message(self):
        return self.args[0]


class SourceNotFound(BuilderFailed):
    pass


class VolumeAlreadyExists(BuilderFailed):
    pass


class CapValidationError(TException):
    template = "Capability {cap} didn't pass validation. Reason: {reason}."


class TaskFailed(PredicateNotSatisfied, TException):
    template = "Task {task} named {name} with id {id} has failed. Reason: {reason}."


class NVMEConnectionFailed(TException):
    template = "NVME connection to {host_nqn} failed"
