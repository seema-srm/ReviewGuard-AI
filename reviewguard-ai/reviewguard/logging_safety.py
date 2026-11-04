"""Context-local SDK log filtering without application-wide suppression."""

from contextlib import contextmanager
from contextvars import ContextVar
import logging
from threading import Lock
from typing import Iterator

_sdk_logs_private: ContextVar[bool] = ContextVar("reviewguard_sdk_logs_private", default=False)
_filter_install_lock = Lock()


class _PrivateSDKFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _sdk_logs_private.get()


_sdk_filter = _PrivateSDKFilter()


@contextmanager
def suppress_sdk_logging() -> Iterator[None]:
    """Suppress only SDK/transport records emitted in this execution context.

    Filters remain attached and pass records in all other contexts. Logger levels,
    handlers and global disable state are untouched. Register existing child
    loggers too, since Python does not apply ancestor filters to propagated logs.
    No request data is stored in the filter or in the process-wide install lock.
    """
    prefixes = ("openai", "httpx", "httpcore")
    with _filter_install_lock:
        names = set(prefixes) | {"openai._base_client", "openai._client"}
        names.update(name for name in list(logging.root.manager.loggerDict)
                     if any(name.startswith(prefix + ".") for prefix in prefixes))
        for name in names:
            logging.getLogger(name).addFilter(_sdk_filter)
    token = _sdk_logs_private.set(True)
    try:
        yield
    finally:
        _sdk_logs_private.reset(token)
