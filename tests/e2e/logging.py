"""e2e logging: shared logger plus pytest progress lines."""
from __future__ import annotations

import sys

from lib.logging import logger

__all__ = ["logger", "progress", "visible"]


def visible(msg: str, config=None) -> None:
    """Always-visible terminal line(s); bypasses pytest capture; does not log.

    Pytest's default FD capture redirects fd 1, so writes to ``sys.__stdout__``
    are still swallowed. Prefer suspending capture via the capturemanager; fall
    back to ``/dev/tty`` (works from sampler background threads without config).
    """
    text = "\n".join(msg.splitlines() or [""])

    cap = None
    if config is not None:
        cap = config.pluginmanager.get_plugin("capturemanager")
    if cap is not None:
        with cap.global_and_fixture_disabled():
            print(text, flush=True)
        return

    try:
        with open("/dev/tty", "w") as tty:
            tty.write(text + "\n")
            tty.flush()
        return
    except OSError:
        pass

    stream = getattr(sys, "__stdout__", None) or sys.stdout
    stream.write(text + "\n")
    stream.flush()


def progress(msg: str, config=None) -> None:
    """Always-visible e2e setup line (pytest capture does not hide it)."""
    logger.info(msg)
    visible(msg, config)
