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


class XprtsecValidationError(Abort):
    """Raised when xprtsec setting is incompatible with view policy or NFS version."""

    def __init__(self, message: str):
        self._message = message

    @property
    def code(self):
        return grpc.StatusCode.INVALID_ARGUMENT

    @property
    def message(self):
        return self._message


class MountFailed(TException):
    template = "Mounting {src} failed"


class UmountTimedOut(Exception):
    """Raised when umount command times out."""
    pass


class FilesystemIntegrityError(Exception):
    """Raised when a filesystem fails its pre-staging integrity/mountability check."""
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


class NoRecordsFound(Exception):
    ...


class WaitResourceFailed(TException, PredicateNotSatisfied):
    template = "resources '{resource}' failed to satisfy {condition} condition"


class PpathConflict(TException):
    template = "Cannot create protected path '{requested_name}': source directory '{source_dir}' is already protected by existing path '{existing_name}'"


class VolumeGroupValidationError(TException):
    template = "Volume group replication requires all volumes to share the same {resource_type}"
