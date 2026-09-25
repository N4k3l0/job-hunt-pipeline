"""Send the app's own log messages to stdout, where Railway shows them.

Uvicorn only sets up its own loggers, so without this every
`logger.info(...)` and `logger.warning(...)` in the app went nowhere: AI
usage, the job reader's counts, and "couldn't tailor the resume" warnings
never reached the logs.
"""

from __future__ import annotations

import logging
import os
import sys

# Log every request at INFO, with full URLs: signed storage links and
# tokens in query strings would end up in the logs.
QUIET = ("httpx", "httpcore", "hpack", "urllib3", "asyncio")

_HANDLER_NAME = "app-stdout"


def setup_logging() -> None:
    """Idempotent: safe to call from every entry point."""
    root = logging.getLogger()
    if not any(h.get_name() == _HANDLER_NAME for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    for name in QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)
