from __future__ import annotations

import logging
from typing import Protocol

import structlog

from video_crawler.core.config import get_settings
from video_crawler.infrastructure.logging.redaction import (
    redact_event,
    redact_processor,
    redact_value,
)


class LoggingSettings(Protocol):
    log_level: str


class RedactingFilter(logging.Filter):
    """Redact stdlib log arguments before logging interpolates them."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_value(record.msg)
        elif isinstance(record.msg, dict):
            record.msg = redact_event(record.msg)
        if isinstance(record.args, dict):
            record.args = redact_event(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(redact_value(value) for value in record.args)
        return True


def configure_logging(settings: LoggingSettings | None = None) -> None:
    """Configure structlog and standard-library logging as redacted JSON."""

    configured = settings or get_settings()
    level = getattr(logging, configured.log_level.upper(), logging.INFO)
    timestamp = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamp,
        redact_processor,
    ]

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
