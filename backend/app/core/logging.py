"""Logging setup. Use the logger from `ctx.log`; never `print`."""

import logging

LOGGER_NAME = "rss"


def get_logger(name: str | None = None) -> logging.Logger:
    """The `rss` logger (or a child of it), configured once with a plain format."""
    root = logging.getLogger(LOGGER_NAME)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    return root if name is None else root.getChild(name)
