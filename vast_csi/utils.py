from collections import defaultdict
import functools
import threading
import re
import grpc
import requests
import json

from pprint import pformat
from plumbum import local
from easypy.decorations import parametrizeable_decorator
from easypy.caching import locking_cache
from easypy.bunch import Bunch

from . logging import logger

LOCKS = defaultdict(lambda: threading.Lock())


class ApiError(Exception):
    pass


class RESTSession(requests.Session):

    def __init__(self, *args, auth, base_url, ssl_verify, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = base_url.rstrip("/")
        self.ssl_verify = ssl_verify
        self.auth = auth
        self.headers["Accept"] = "application/json"
        self.headers["Content-Type"] = "application/json"

    def request(self, verb, api_method, *, params=None, **kwargs):
        verb = verb.upper()
        api_method = api_method.strip("/")
        url = f"{self.base_url}/{api_method}/"
        logger.info(f">>> [{verb}] {url}")

        if 'data' in kwargs:
            kwargs['data'] = json.dumps(kwargs['data'])

        if params or kwargs:
            for line in pformat(dict(kwargs, params=params)).splitlines():
                logger.info(f"    {line}")

        ret = super().request(verb, url, verify=self.ssl_verify, params=params, **kwargs)

        if ret.status_code == 503 and ret.text:
            logger.error(ret.text)
            raise ApiError(ret.text)

        ret.raise_for_status()

        logger.info(f"<<< [{verb}] {url}")
        if ret.content:
            ret = Bunch.from_dict(ret.json())
            for line in pformat(ret).splitlines():
                logger.info(f"    {line}")
        else:
            ret = None
        logger.info(f"--- [{verb}] {url}: Done")
        return ret

    def __getattr__(self, attr):
        if attr.startswith("_"):
            raise AttributeError(attr)

        def func(**params):
            return self.request("get", attr, params=params)

        func.__name__ = attr
        func.__qualname__ = f"{self.__class__.__qualname__}.{attr}"
        setattr(self, attr, func)
        return func


@parametrizeable_decorator
def unique(func, key_name):
    method_name = func.__name__
    lock = LOCKS[method_name]
    workers = {}

    @functools.wraps(func)
    def wrapper(self, request, context):
        worker_key = getattr(request, key_name)
        my_thread = threading.current_thread().ident

        with lock:
            actual = workers.setdefault(worker_key, my_thread)

            if actual != my_thread:
                context.abort(
                    grpc.StatusCode.ABORTED,
                    f'thread {actual} is already performing {method_name} on {worker_key}')

            try:
                return func(self, request, context)
            finally:
                del workers[worker_key]

    return wrapper


PATH_ALIASES = {
    re.compile('.*/site-packages'): '*',
    re.compile("%s/" % local.cwd): ''
}


@locking_cache
def clean_path(path):
    path = str(local.path(path))  # absolutify
    for regex, alias in PATH_ALIASES.items():
        path = regex.sub(alias, path)
    return path


def nice_format_traceback(self):

    _RECURSIVE_CUTOFF = 3

    if True:  # indent like the original code in the traceback module
        result = []
        last_file = None
        last_line = None
        last_name = None
        count = 0

        lines = []

        for frame in self:
            if (last_file is None or last_file != frame.filename or
                last_line is None or last_line != frame.lineno or
                last_name is None or last_name != frame.name):
                if count > _RECURSIVE_CUTOFF:
                    count -= _RECURSIVE_CUTOFF
                    result.append(
                        f'  [Previous line repeated {count} more '
                        f'time{"s" if count > 1 else ""}]\n'
                    )
                last_file = frame.filename
                last_line = frame.lineno
                last_name = frame.name
                count = 0
            count += 1
            if count > _RECURSIVE_CUTOFF:
                continue

            filename, lineno, name, line = frame.filename, frame.lineno, frame.name, frame.line

            filename = clean_path(filename)
            left = f"  {filename}:{lineno} "
            right = f" {name}"

            blame = None  # can't 'blame' inside the infra container

            lines.append((len(left) + len(right), len(line), left, right, line, blame))
            if frame.locals:
                for name, value in sorted(frame.locals.items()):
                    line = f"{name} = {value}"
                    lines.append((len(left) + len(right), 0, '', '', line, ''))

        lwidth = max((args[0] for args in lines), default=0) + 4
        rwidth = max((args[1] for args in lines), default=0) + 2

        for _, _, left, right, line, blame in lines:
            item = left.ljust(lwidth - len(right), ".") + right
            if line:
                item = f'{item} >> {line.strip():{rwidth}}'
                if blame:
                    item += blame
            result.append(item + '\n')

        if count > _RECURSIVE_CUTOFF:
            count -= _RECURSIVE_CUTOFF
            result.append(
                f'  [Previous line repeated {count} more '
                f'time{"s" if count > 1 else ""}]\n'
            )
        return result


def patch_traceback_format():
    from traceback import StackSummary
    orig_format_traceback, StackSummary.format = StackSummary.format, nice_format_traceback
