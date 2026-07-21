from __future__ import annotations

import logging
from typing import Any

from video_crawler.core.config import get_settings
from video_crawler.infrastructure.logging.redaction import redact_event


def configure_logging(settings: Any | None = None) -> None:
    """Configure root logging and attach a filter that redacts sensitive data in records."""
    settings = settings or get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # try to redact if record.args is a mapping
            if isinstance(record.args, dict):
                record.args = tuple(redact_event(record.args).values())
        except Exception as exc:  # defensive: do not let logging fail
            logging.getLogger(__name__).debug("redaction filter failed", exc_info=exc)
        return True


def attach_redaction() -> None:
    logging.getLogger().addFilter(RedactingFilter())
