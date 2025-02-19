import logging
from plumbum.commands.modifiers import PipeToLoggerMixin


@logging.setLoggerClass
class Logger(logging.Logger, PipeToLoggerMixin):
    pass


logger = logging.getLogger("vast-csi")


def init_logging(level):
    logging.basicConfig(
        level=level.upper(),
        format="{asctime}|{levelname:7}|{thread:X}|{name:15}| {message}",
        style="{"
    )
