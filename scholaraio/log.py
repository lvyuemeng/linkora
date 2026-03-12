"""ScholarAIO Logging Module.

Three-layer output:
  1. File log (RotatingFileHandler) - DEBUG level, complete records
  2. Console output (StreamHandler) - INFO level, print-like format
  3. ui() function - print() drop-in replacement, writes to both
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

# Explicit level mapping - no getattr metaprogramming
_LOG_LEVELS: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


class HasLogConfig(Protocol):
    """Protocol for log configuration."""

    @property
    def log_file(self) -> Path: ...

    @property
    def level(self) -> str: ...

    @property
    def max_bytes(self) -> int: ...

    @property
    def backup_count(self) -> int: ...


@dataclass
class LogSettings:
    """Log configuration dataclass."""

    level: str = "INFO"
    max_bytes: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 3


# Format: file handler gets timestamp+module+level; console gets bare message
_FILE_FMT = "%(asctime)s %(name)-24s %(levelname)-5s %(message)s"
_FILE_DATEFMT = "%Y-%m-%d %H:%M:%S"
_CONSOLE_FMT = "%(message)s"


def _resolve_level(level: str) -> int:
    """Resolve string level to logging constant."""
    return _LOG_LEVELS.get(level.lower(), logging.INFO)


class LoggerManager:
    """Singleton logger manager with session tracking.

    Encapsulates all logging state - no global mutable state.
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
        """Current session ID (empty before setup)."""
        return self._session_id

    @property
    def is_initialized(self) -> bool:
        """Whether logger has been initialized."""
        return self._initialized

    def setup(self, cfg: HasLogConfig) -> str:
        """Initialize root logger, return session_id for this session.

        Args:
            cfg: ScholarAIO configuration with log settings.

        Returns:
            UUID4 session_id for associating metrics events.
        """
        if self._initialized:
            return self._session_id

        self._session_id = uuid.uuid4().hex[:12]

        root = logging.getLogger()
        root.setLevel(logging.DEBUG)

        # -- File handler (DEBUG, rotating) --
        log_path = cfg.log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=cfg.max_bytes,
            backupCount=cfg.backup_count,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(_FILE_FMT, datefmt=_FILE_DATEFMT))
        root.addHandler(fh)

        # -- Console handler (INFO, bare message) --
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(_resolve_level(cfg.level))
        ch.setFormatter(logging.Formatter(_CONSOLE_FMT))
        root.addHandler(ch)

        # Suppress noisy third-party loggers
        for name in (
            "httpx",
            "urllib3",
            "modelscope",
            "httpcore",
            "sentence_transformers",
        ):
            logging.getLogger(name).setLevel(logging.WARNING)

        self._initialized = True
        logging.getLogger(__name__).debug("session %s started", self._session_id)
        return self._session_id

    def get_logger(self, name: str) -> logging.Logger:
        """Get logger instance by name.

        Args:
            name: Logger name, typically __name__.

        Returns:
            Logger instance.
        """
        return logging.getLogger(name)

    def ui(self, msg: str = "", *args, logger: logging.Logger | None = None) -> None:
        """User interface output - print() drop-in replacement.

        Writes to both console and log file.

        Args:
            msg: Message string with % formatting placeholders.
            *args: Format arguments.
            logger: Specific logger, defaults to scholaraio.ui.
        """
        _logger = logger or logging.getLogger("scholaraio.ui")
        _logger.info(msg, *args)

    def reset(self) -> None:
        """Reset logger state (for testing only)."""
        root = logging.getLogger()
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()
        self._session_id = ""
        self._initialized = False


# Singleton instance for module-level functions
_logger_manager = LoggerManager()


# Module-level convenience functions (delegated to singleton)
def setup(cfg: HasLogConfig) -> str:
    """Initialize root logger, return session_id for this session."""
    return _logger_manager.setup(cfg)


def get_session_id() -> str:
    """Return current session ID (empty before setup)."""
    return _logger_manager.session_id


def get_logger(name: str) -> logging.Logger:
    """Shortcut for logging.getLogger(name)."""
    return _logger_manager.get_logger(name)


def ui(msg: str = "", *args, logger: logging.Logger | None = None) -> None:
    """User interface output - print() drop-in replacement."""
    _logger_manager.ui(msg, *args, logger=logger)


def reset() -> None:
    """Reset logger state (for testing only)."""
    _logger_manager.reset()
