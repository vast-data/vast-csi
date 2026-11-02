import logging
from easypy.logging import initialize as init_easypy_logging
from plumbum.commands.modifiers import PipeToLoggerMixin


class Logger(logging.Logger, PipeToLoggerMixin):
    pass


logging.setLoggerClass(Logger)


logger = logging.getLogger("vast-csi")


def init_logging(level):
    logging.basicConfig(
        level=level.upper(),
        format="{asctime}|{levelname:7}|{thread:X}|{name:15}| {message}",
        style="{"
    )
    # Until initialized, easypy logs into a class-level MagicMock that keeps every call forever.
    init_easypy_logging(coloring=False)
