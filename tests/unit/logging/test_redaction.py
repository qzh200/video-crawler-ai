from __future__ import annotations

import json
import logging

import structlog

from video_crawler.infrastructure.logging.config import configure_logging
from video_crawler.infrastructure.logging.redaction import REDACTED, redact_event


def test_redact_event_recursively_removes_sensitive_values_without_mutation() -> None:
    raw = {
        "Cookie": "session=abcd1234; other=val",
        "headers": {
            "Authorization": "Bearer secret-token-xyz",
            "x-api-key": "supersecret",
            "author_name": "public-author",
        },
        "url": ("https://example.test/path?token=abc123&signature=signed-value&other=1"),
        "nested": [
            {"password": "hunter2"},
            "Cookie: session=nested-cookie\nnext line",
            {"refresh_token": "refresh-secret"},
        ],
    }

    redacted = redact_event(raw)
    serialized = json.dumps(redacted)

    for secret in (
        "abcd1234",
        "secret-token-xyz",
        "supersecret",
        "abc123",
        "signed-value",
        "hunter2",
        "nested-cookie",
        "refresh-secret",
    ):
        assert secret not in serialized
    assert redacted["Cookie"] == REDACTED
    assert redacted["headers"]["author_name"] == "public-author"
    assert raw["headers"]["Authorization"] == "Bearer secret-token-xyz"


def test_configure_logging_outputs_redacted_json(capsys) -> None:
    class Settings:
        log_level = "INFO"

    configure_logging(Settings())  # type: ignore[arg-type]
    structlog.get_logger("test").info(
        "request_complete",
        request_id="request-1",
        headers={"Authorization": "Bearer never-log-this"},
    )
    logging.getLogger("dependency").info("payload=%s", {"password": "stdlib-secret"})

    output = capsys.readouterr().err.strip()
    lines = output.splitlines()
    event = json.loads(lines[0])
    assert event["event"] == "request_complete"
    assert event["request_id"] == "request-1"
    assert event["headers"]["Authorization"] == REDACTED
    assert "never-log-this" not in output
    assert "stdlib-secret" not in output
    assert REDACTED in json.loads(lines[1])["event"]
