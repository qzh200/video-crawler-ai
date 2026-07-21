from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from video_crawler.api.dependencies.auth import require_api_key


class _DummySecret:
    def __init__(self, v: str) -> None:
        self._v = v

    def get_secret_value(self) -> str:
        return self._v


def _make_settings(api_key_enabled: bool, api_key_value: str):
    class S:
        pass

    s = S()
    s.api_key_enabled = api_key_enabled
    s.api_key = _DummySecret(api_key_value)
    return s


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/ping", dependencies=[Depends(require_api_key)])
    def ping() -> dict:
        return {"ok": True}

    return app


def test_api_key_disabled_allows_requests(monkeypatch) -> None:
    settings = _make_settings(api_key_enabled=False, api_key_value="does-not-matter")
    monkeypatch.setattr("video_crawler.api.dependencies.auth.get_settings", lambda: settings)

    app = _make_app()
    client = TestClient(app)

    r = client.get("/api/v1/ping")
    assert r.status_code == 200


def test_api_key_enabled_rejects_missing_and_wrong(monkeypatch) -> None:
    settings = _make_settings(api_key_enabled=True, api_key_value="correct-key")
    monkeypatch.setattr("video_crawler.api.dependencies.auth.get_settings", lambda: settings)

    app = _make_app()
    client = TestClient(app)

    r = client.get("/api/v1/ping")
    assert r.status_code == 401

    r2 = client.get("/api/v1/ping", headers={"X-API-Key": "wrong"})
    assert r2.status_code == 401


def test_api_key_enabled_accepts_correct(monkeypatch) -> None:
    settings = _make_settings(api_key_enabled=True, api_key_value="correct-key")
    monkeypatch.setattr("video_crawler.api.dependencies.auth.get_settings", lambda: settings)

    app = _make_app()
    client = TestClient(app)

    r = client.get("/api/v1/ping", headers={"X-API-Key": "correct-key"})
    assert r.status_code == 200
