"""Logging helpers that stand in for slash's logger (notice, indented, pipe)."""
from __future__ import annotations

import logging
from contextlib import contextmanager

from easypy.logging import initialize as init_easypy_logging
from vast_csi.logging import init_logging

init_easypy_logging(coloring=False)

logger = logging.getLogger("csi-e2e")

if not logging.getLogger().handlers:
    init_logging("INFO")


def _notice(msg, *args, **kwargs):
    logger.info(msg, *args, **kwargs)


logger.notice = _notice


@contextmanager
def _indented(msg):
    logger.info(msg)
    yield


logger.indented = _indented


def progress(msg: str, config=None) -> None:
    """Always-visible e2e setup line (pytest capture does not hide it)."""
    logger.info(msg)
    reporter = None
    if config is not None:
        reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(f"[e2e] {msg}")
    else:
        print(f"[e2e] {msg}", flush=True)
