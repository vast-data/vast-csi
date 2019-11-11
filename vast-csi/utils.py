from collections import defaultdict
import functools
import threading
import grpc
from easypy.decorations import parametrizeable_decorator


LOCKS = defaultdict(lambda: threading.Lock())


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
