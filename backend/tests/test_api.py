import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from tests.conftest import make_jpeg


@pytest.fixture
def client():
    return TestClient(create_app(Settings(mock_mode=True)))


def client_for(scenario: str) -> TestClient:
    return TestClient(create_app(Settings(mock_mode=True, mock_scenario=scenario)))


def files(*names):
    return [("images", (n, make_jpeg(), "image/jpeg")) for n in names]


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "mock_mode": True, "vision_provider": "mock"}


def test_health_live_reports_provider():
    app = create_app(Settings(mock_mode=False, vision_provider="gemini", gemini_api_key="k",
                              google_places_api_key="g"))
    assert TestClient(app).get("/api/health").json() == {"status": "ok", "mock_mode": False,
                                                         "vision_provider": "gemini"}


def test_place_cards_happy_path():
    client = client_for("leopold,gateway,generic")  # mock vision by photo order, not filename
    meta = [{"index": 0, "hint": "Colaba, Mumbai"}, {"index": 2, "lat": 18.92298, "lng": 72.83187}]
    r = client.post("/api/place-cards",
                    files=files("IMG_0001.jpg", "IMG_0002.jpg", "IMG_0003.jpg"),
                    data={"meta": json.dumps(meta), "global_hint": "Mumbai"})
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    by_pid = {x["card"]["place_id"]: x for x in results if x["card"]}
    assert by_pid["mock_leopold_cafe"]["photo_indexes"] == [0, 2]  # merged: vision photo + GPS photo
    assert by_pid["mock_gateway_of_india"]["card"]["category"] == "landmark"
    card = by_pid["mock_gateway_of_india"]["card"]
    assert card["attribution"] == "Google Maps" and len(card["nearby"]) == 3
    assert '"lat"' not in json.dumps(results) and '"latitude"' not in json.dumps(results) and '"lng"' not in json.dumps(results)
    # contract keys (Section 4.1)
    expected = {"place_id", "name", "category", "is_restaurant", "summary", "address", "area", "rating",
                "rating_count", "price_level", "price_label", "open_now", "hours_today", "reviews", "nearby",
                "website", "maps_url", "photo_indexes", "confidence", "source", "attribution"}
    assert set(card) == expected


def test_place_cards_without_meta():
    client = client_for("ambiguous,generic")
    r = client.post("/api/place-cards", files=files("IMG_1.jpg", "IMG_2.jpg"))
    assert r.status_code == 200
    statuses = sorted(x["status"] for x in r.json()["results"])
    assert statuses == ["low_confidence", "not_found"]


def test_filename_does_not_change_detection():
    a = client_for("leopold").post("/api/place-cards", files=files("leopold.jpg")).json()
    b = client_for("leopold").post("/api/place-cards", files=files("IMG_4821.jpg")).json()
    c = client_for("generic").post("/api/place-cards", files=files("leopold.jpg")).json()
    assert a == b  # same scenario, different filename -> same result
    assert a["results"][0]["status"] == "ok" and c["results"][0]["status"] == "not_found"


def test_default_mock_order_without_setting(client):
    r = client.post("/api/place-cards", files=files("a.jpg", "b.jpg", "c.jpg", "d.jpg"))
    statuses = [x["status"] for x in r.json()["results"]]
    assert statuses == ["ok", "ok", "low_confidence", "not_found"]  # leopold, gateway, ambiguous, generic


def test_no_images_is_400(client):
    r = client.post("/api/place-cards", data={"global_hint": "x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_images"


def test_too_many_images_is_400(client):
    r = client.post("/api/place-cards", files=files(*[f"{i}.jpg" for i in range(11)]))
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_many_images"


def test_image_too_large_is_413(client):
    big = [("images", ("big.jpg", b"\xff\xd8\xff" + b"0" * (2 * 1024 * 1024 + 10), "image/jpeg"))]
    r = client.post("/api/place-cards", files=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "image_too_large"


def test_invalid_image_is_400(client):
    r = client.post("/api/place-cards", files=[("images", ("a.jpg", b"not an image", "image/jpeg"))])
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_image"


@pytest.mark.parametrize("meta", [
    "not json", '{"index": 0}', '[{"index": 5}]', '[{"index": 0}, {"index": 0}]',
    '[{"index": 0, "lat": 999, "lng": 0}]', '["x"]',
])
def test_bad_meta_is_400(client, meta):
    r = client.post("/api/place-cards", files=files("a.jpg"), data={"meta": meta})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_meta"


def test_resolve_by_query(client):
    r = client.post("/api/place-cards/resolve", json={"query": "Cafe Leopold", "hint": "Mumbai"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["card"]["source"] == "user"


def test_resolve_by_place_id(client):
    r = client.post("/api/place-cards/resolve", json={"place_id": "mock_madras_pune"})
    assert r.status_code == 200 and r.json()["card"]["place_id"] == "mock_madras_pune"


def test_resolve_candidates(client):
    r = client.post("/api/place-cards/resolve", json={"query": "Cafe Madras"})
    body = r.json()
    assert body["status"] == "low_confidence" and len(body["candidates"]) == 3 and body["card"] is None


def test_resolve_requires_query_or_place_id(client):
    r = client.post("/api/place-cards/resolve", json={"hint": "Mumbai"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "missing_query"


def test_resolve_validation_error_shape(client):
    r = client.post("/api/place-cards/resolve", json={"query": "x", "lat": 500, "lng": 0})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_unknown_route_has_error_json(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "http_error"


def test_cors_allows_configured_origin(client):
    r = client.options("/api/place-cards", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    r2 = client.options("/api/place-cards", headers={
        "Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r2.headers


def test_live_mode_without_keys_fails_fast():
    with pytest.raises(RuntimeError):
        create_app(Settings(mock_mode=False))


@pytest.mark.parametrize("kwargs,missing", [
    (dict(vision_provider="gemini", google_places_api_key="g"), "GEMINI_API_KEY"),
    (dict(vision_provider="anthropic", google_places_api_key="g"), "ANTHROPIC_API_KEY"),
    (dict(vision_provider="gemini", gemini_api_key="k"), "GOOGLE_PLACES_API_KEY"),
    (dict(vision_provider="nope", google_places_api_key="g"), "VISION_PROVIDER"),
])
def test_live_mode_missing_key_names_the_variable_and_never_falls_back_to_mock(kwargs, missing):
    with pytest.raises(RuntimeError, match=missing):
        create_app(Settings(mock_mode=False, **kwargs))


def test_live_mode_builds_selected_provider():
    from app.services.vision import AnthropicVision, GeminiVision
    g = create_app(Settings(mock_mode=False, vision_provider="gemini", gemini_api_key="k",
                            google_places_api_key="g"))
    a = create_app(Settings(mock_mode=False, vision_provider="anthropic", anthropic_api_key="k",
                            google_places_api_key="g"))
    assert isinstance(g.state.resolver.vision, GeminiVision)
    assert isinstance(a.state.resolver.vision, AnthropicVision)
