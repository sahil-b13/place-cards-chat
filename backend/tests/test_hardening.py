import json
import os
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_settings
from app.hardening import RateLimiter
from app.main import create_app
from app.services.places import PlacesClient, PlacesError
from tests.conftest import make_jpeg

ORIGIN = "http://localhost:5173"


def client(**kw):
    return TestClient(create_app(Settings(mock_mode=True, **kw)))


# ---------------- rate limiter ----------------

def test_limiter_window_and_retry_after():
    now = [0.0]
    lim = RateLimiter(2, 60, clock=lambda: now[0])
    assert lim.check("a") == (True, 0) and lim.check("a") == (True, 0)
    ok, retry = lim.check("a")
    assert not ok and 1 <= retry <= 61
    assert lim.check("b")[0]  # other clients unaffected
    now[0] = 61
    assert lim.check("a")[0]  # window slid


def test_limiter_disabled_when_zero():
    lim = RateLimiter(0)
    assert all(lim.check("a")[0] for _ in range(100))


def test_api_returns_429_json_with_retry_after_and_cors():
    c = client(rate_limit_per_minute=3)
    body = {"query": "Cafe Leopold", "hint": "Mumbai"}
    for _ in range(3):
        assert c.post("/api/place-cards/resolve", json=body, headers={"Origin": ORIGIN}).status_code == 200
    r = c.post("/api/place-cards/resolve", json=body, headers={"Origin": ORIGIN})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited" and int(r.headers["retry-after"]) >= 1
    assert r.headers["access-control-allow-origin"] == ORIGIN  # the browser can read the error message


def test_health_and_preflight_are_not_rate_limited():
    c = client(rate_limit_per_minute=1)
    for _ in range(5):
        assert c.get("/api/health").status_code == 200
        pre = c.options("/api/trip-plan", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                                                    "Access-Control-Request-Headers": "content-type"})
        assert pre.status_code == 200


def test_proxy_header_only_trusted_when_enabled():
    body = {"query": "Cafe Leopold"}
    # untrusted: spoofing X-Forwarded-For must not give a fresh budget
    c = client(rate_limit_per_minute=1, trust_proxy=False)
    assert c.post("/api/place-cards/resolve", json=body, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert c.post("/api/place-cards/resolve", json=body, headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429
    # trusted: the rightmost entry (added by our proxy) identifies the client
    c = client(rate_limit_per_minute=1, trust_proxy=True)
    assert c.post("/api/place-cards/resolve", json=body, headers={"X-Forwarded-For": "9.9.9.9, 1.1.1.1"}).status_code == 200
    assert c.post("/api/place-cards/resolve", json=body, headers={"X-Forwarded-For": "8.8.8.8, 2.2.2.2"}).status_code == 200
    assert c.post("/api/place-cards/resolve", json=body, headers={"X-Forwarded-For": "7.7.7.7, 1.1.1.1"}).status_code == 429


# ---------------- request size ----------------

def test_oversized_json_and_multipart_rejected_early():
    c = client(rate_limit_per_minute=0)
    big = {"query": "x" * 70_000}
    r = c.post("/api/place-cards/resolve", json=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "request_too_large"
    # multipart cap = max_images * max_image_bytes + overhead: claim a huge body via Content-Length
    r = c.post("/api/place-cards", content=b"x", headers={"Content-Type": "multipart/form-data; boundary=x",
                                                          "Content-Length": str(200 * 1024 * 1024)})
    assert r.status_code == 413


def test_normal_upload_still_works_and_headers_set():
    c = client(rate_limit_per_minute=0)
    r = c.post("/api/place-cards", files=[("images", ("IMG_1.jpg", make_jpeg(), "image/jpeg"))])
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"


def test_bad_content_length_is_400():
    r = client().post("/api/trip-plan", content=b"{}", headers={"Content-Length": "abc", "Content-Type": "application/json"})
    assert r.status_code in (400, 422)


# ---------------- Places retry ----------------

def _places(handler):
    return PlacesClient("SECRET-KEY-123", transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_places_retries_once_on_503_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={"places": []})

    assert await _places(handler).search_text("x") == []
    assert len(calls) == 2


@pytest.mark.anyio
async def test_places_retries_on_timeout_and_gives_up_cleanly():
    calls = []

    def handler(req):
        calls.append(1)
        raise httpx.ConnectTimeout("boom")

    with pytest.raises(PlacesError) as e:
        await _places(handler).search_text("x")
    assert len(calls) == 2 and "SECRET-KEY-123" not in str(e.value)


@pytest.mark.anyio
async def test_places_does_not_retry_client_errors():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(403)

    with pytest.raises(PlacesError):
        await _places(handler).search_text("x")
    assert len(calls) == 1


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------- privacy ----------------

def test_trip_plan_response_has_no_coordinates():
    c = client(rate_limit_per_minute=0)
    r = c.post("/api/trip-plan", json={"place_ids": ["mock_gateway_of_india", "mock_csmt", "mock_marine_drive"],
                                       "start": {"text": "Colaba, Mumbai"}})
    assert r.status_code == 200
    assert not re.search(r'"(lat|lng|latitude|longitude|location|origin)"', json.dumps(r.json()))


def test_backend_never_writes_files_or_stores_images():
    """Uploaded images are processed in memory only: no tempfile use, no file writes, no image saves in app/."""
    root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app")
    offenders = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            if not f.endswith(".py"):
                continue
            src = open(os.path.join(dirpath, f), encoding="utf-8").read()
            if re.search(r"tempfile|shutil|\.write_bytes|\.write_text|\.save\(|open\([^)]*['\"][wax]b?\+?['\"]", src):
                offenders.append(f)
    assert offenders == []


def test_load_settings_reads_hosting_vars(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "7")
    monkeypatch.setenv("TRUST_PROXY", "true")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    s = load_settings()
    assert (s.rate_limit_per_minute, s.trust_proxy, s.log_level) == (7, True, "DEBUG")
