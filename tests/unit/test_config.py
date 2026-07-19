from video_crawler.core.config import Settings


def test_settings_rejects_invalid_delay_range() -> None:
    try:
        Settings(
            mysql_password="x",  # noqa: S106 - synthetic test credential
            minio_secret_key="x",  # noqa: S106 - synthetic test credential
            api_key="x",
            default_video_delay_min_seconds=3.0,
            default_video_delay_max_seconds=1.0,
        )
    except ValueError as exc:
        assert "video delay min" in str(exc)
    else:
        raise AssertionError("Settings must reject min > max")
