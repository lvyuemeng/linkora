"""
log.py — linkora logging module.

Three output layers:
  1. File log  (RotatingFileHandler) — DEBUG level, complete records
  2. Console   (StreamHandler)       — configurable level, bare message
  3. ui()                            — print() drop-in, writes to both

Setup
─────
Call ``setup(log_config, log_file)`` once at process startup.
``log_file`` is a ``Path`` — callers obtain it from
``WorkspacePaths.log_file(cfg.log.file)`` so that log placement is
governed by workspace path logic, not by this module.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from linkora.config import LogConfig

# ---------------------------------------------------------------------------
# Level map  (explicit — no getattr metaprogramming)
# ---------------------------------------------------------------------------

_LOG_LEVELS: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

_FILE_FMT = "%(asctime)s %(name)-24s %(levelname)-5s %(message)s"
_FILE_DATEFMT = "%Y-%m-%d %H:%M:%S"
_CONSOLE_FMT = "%(message)s"

# Third-party loggers that produce excessive noise at DEBUG/INFO.
_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "modelscope",
    "sentence_transformers",
)


def _resolve_level(level: str) -> int:
    return _LOG_LEVELS.get(level.lower(), logging.INFO)


# ---------------------------------------------------------------------------
# LoggerManager  (process singleton)
# ---------------------------------------------------------------------------


class LoggerManager:
    """
    Process-wide logging state.

    Encapsulates all mutable logging state so there is no implicit
    global state in module scope.  A single singleton instance is
    created at import time and exposed through module-level functions.
    """

    _instance: "LoggerManager | None" = None
    _session_id: str = ""
    _initialized: bool = False

    def __new__(cls) -> "LoggerManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def session_id(self) -> str:
        """Current session ID (empty string before ``setup()`` is called)."""
        return self._session_id

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def setup(self, log_config: "LogConfig", log_file: Path) -> str:
        """
        Configure the root logger and return a new session ID.

        Must be called once at process startup after the active workspace
        is known.  Subsequent calls are no-ops and return the existing
        session ID.

        Parameters
        ----------
        log_config:
            ``AppConfig.log`` — carries level, max_bytes, backup_count.
        log_file:
            Absolute path to the rotating log file.  Obtain via
            ``WorkspacePaths.log_file(log_config.file)``.

        Returns
        -------
        str
            A 12-character hex session ID for correlating metrics events.
        """
        if self._initialized:
            return self._session_id

        self._session_id = uuid.uuid4().hex[:12]

        root = logging.getLogger()
        root.setLevel(logging.DEBUG)

        # File handler — DEBUG, rotating.
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=log_config.max_bytes,
            backupCount=log_config.backup_count,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(_FILE_FMT, datefmt=_FILE_DATEFMT))
        root.addHandler(fh)

        # Console handler — user-configured level, bare message.
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(_resolve_level(log_config.level))
        ch.setFormatter(logging.Formatter(_CONSOLE_FMT))
        root.addHandler(ch)

        # Silence noisy third-party loggers.
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

        self._initialized = True
        logging.getLogger(__name__).debug("session %s started", self._session_id)
        return self._session_id

    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)

    def ui(
        self, msg: str = "", *args: object, logger: logging.Logger | None = None
    ) -> None:
        """
        User-interface output — a ``print()`` drop-in that also writes to
        the log file.

        Parameters
        ----------
        msg:
            Message string, optionally with ``%``-style placeholders.
        *args:
            Format arguments.
        logger:
            Specific logger instance; defaults to ``linkora.ui``.
        """
        _logger = logger or logging.getLogger("linkora.ui")
        _logger.info(msg, *args)

    def reset(self) -> None:
        """Reset all handlers — intended for tests only."""
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()
        self._session_id = ""
        self._initialized = False


# ---------------------------------------------------------------------------
# Singleton + module-level convenience API
# ---------------------------------------------------------------------------

_manager = LoggerManager()


def init(log_config: "LogConfig", log_file: Path) -> str:
    """
    Configure the root logger.

    Parameters
    ----------
    log_config:
        ``AppConfig.log`` — level, rotation settings.
    log_file:
        Absolute path to the rotating log file.

    Returns
    -------
    str
        Session ID for correlating metrics events.
    """
    return _manager.setup(log_config, log_file)


def get_session_id() -> str:
    """Return the current session ID (empty before ``setup()`` is called)."""
    return _manager.session_id


def get_logger(name: str) -> logging.Logger:
    """Return a named logger — shorthand for ``logging.getLogger(name)``."""
    return _manager.get_logger(name)


def ui(msg: str = "", *args: object, logger: logging.Logger | None = None) -> None:
    """User-interface output — ``print()`` drop-in that also writes to the log."""
    _manager.ui(msg, *args, logger=logger)


def reset() -> None:
    """Reset logging state — for tests only."""
    _manager.reset()
