import logging
from plumbum.commands.modifiers import PipeToLoggerMixin


@logging.setLoggerClass
class Logger(logging.Logger, PipeToLoggerMixin):
    pass


logger = logging.getLogger("vast-csi")


def init_logging():
    logging.basicConfig(
        level=0,
        format="{asctime}|{levelname:7}|{thread:X}|{name:15}| {message}",
        style="{"
    )
