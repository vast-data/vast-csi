"""Shared logger for CSI tests (e2e and certification)."""
from __future__ import annotations

import logging
from contextlib import contextmanager

from easypy.logging import initialize as init_easypy_logging
from vast_csi.logging import init_logging

init_easypy_logging(coloring=False)

logger = logging.getLogger("csi-tests")

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
