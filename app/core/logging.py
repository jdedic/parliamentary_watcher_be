import sys
import logging
import datetime
from pathlib import Path
import structlog
from app.core.config import BASE_DIR, settings

LOGS_DIR = BASE_DIR / "logs"


class DailyFileHandler(logging.FileHandler):
    """Writes to logs/YYYY-MM-DD.log, opening a new file automatically each day."""

    def _today_path(self) -> Path:
        return LOGS_DIR / f"{datetime.date.today().isoformat()}.log"

    def emit(self, record: logging.LogRecord) -> None:
        today = str(self._today_path().resolve())
        if self.baseFilename != today:
            self.close()
            self.baseFilename = today
            self.stream = self._open()
        super().emit(record)


def setup_logging() -> None:
    """Configure structlog for structured JSON logging.

    Three handlers are attached to the root logger:
      - stdout: INFO and above (general operational messages)
      - stderr: ERROR and above (failures that need attention)
      - file: daily rotating log file in logs/YYYY-MM-DD.log
    """

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    formatter = logging.Formatter("%(message)s")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(log_level)
    stdout_handler.setFormatter(formatter)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(formatter)

    LOGS_DIR.mkdir(exist_ok=True)
    file_handler = DailyFileHandler(
        filename=LOGS_DIR / f"{datetime.date.today().isoformat()}.log",
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(stderr_handler)
    root_logger.addHandler(file_handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer()
            if settings.environment == "production"
            else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a named structlog logger instance."""
    return structlog.get_logger(name)
