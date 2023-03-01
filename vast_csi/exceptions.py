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
