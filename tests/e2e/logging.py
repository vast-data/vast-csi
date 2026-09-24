"""e2e logging: shared logger plus pytest progress lines."""
from lib.logging import logger

__all__ = ["logger", "progress"]


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
