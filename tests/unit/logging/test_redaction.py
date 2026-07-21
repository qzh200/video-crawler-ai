from video_crawler.infrastructure.logging.redaction import redact_event


def test_redact_sensitive_keys_and_values() -> None:
    raw = {
        "Cookie": "session=abcd1234; other=val",
        "headers": {
            "Authorization": "Bearer secret-token-xyz",
            "x-api-key": "supersecret",
        },
        "url": "https://example.test/path?token=abc123&other=1",
        "nested": [
            {"password": "hunter2"},
            "normal",
            {"list_token": "should-not-match"},
        ],
    }

    redacted = redact_event(raw)

    # sensitive keys should be redacted
    assert redacted["Cookie"] == "<redacted>"
    assert redacted["headers"]["Authorization"] == "<redacted>"
    assert redacted["headers"]["x-api-key"] == "<redacted>"
    assert redacted["nested"][0]["password"] == "<redacted>"  # noqa: S105

    # token in URL query should be sanitized
    assert "abc123" not in redacted["url"]
    # non-sensitive values preserved
    assert "normal" in redacted["nested"]
