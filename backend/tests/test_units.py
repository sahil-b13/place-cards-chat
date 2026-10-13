import asyncio
import json

import httpx
import pytest
from PIL import Image

from app.schemas import PlaceDetails, Review
from app.services import card_builder
from app.services.cache import TTLCache
from app.services.exif import extract_gps
from app.services.places import (DETAILS_MASK, PlacesClient, PlacesError, haversine_m, parse_details)
from app.services.vision import AnthropicVision, GeminiVision, VisionError, parse_vision_json

from tests.conftest import make_jpeg


def run(coro):
    return asyncio.run(coro)


# ---- card builder ----

def _details(**kw):
    base = dict(place_id="p1", name="Test Place", address="1 Main St, Colaba, Mumbai, Maharashtra 400001, India",
                types=["restaurant"], primary_type="restaurant", maps_url="https://maps.example/p1")
    base.update(kw)
    return PlaceDetails(**base)


def test_price_label_mapping():
    assert card_builder.price_label(0) == "Free"
    assert [card_builder.price_label(i) for i in (1, 2, 3, 4)] == ["₹", "₹₹", "₹₹₹", "₹₹₹₹"]
    assert card_builder.price_label(None) is None


def test_truncation_and_limits():
    long_review = "x" * 500
    d = _details(
        editorial_summary="s" * 500,
        reviews=[Review(author="a", rating=5, text=long_review) for _ in range(6)],
        price_level=2,
    )
    from app.schemas import NearbyItem
    nearby = [NearbyItem(name=f"n{i}") for i in range(6)]
    c = card_builder.build_card(d, "landmark", nearby, [2, 0, 2], "high", "exif")
    assert len(c.summary) <= 200 and c.summary.endswith("…")
    assert len(c.reviews) == 3 and all(len(r.text) <= 160 for r in c.reviews)
    assert len(c.nearby) == 3
    assert c.photo_indexes == [0, 2]
    assert c.price_label == "₹₹" and c.attribution == "Google Maps"


def test_card_is_small_and_has_no_coordinates():
    d = _details(lat=1.234, lng=5.678, editorial_summary="s" * 500,
                 reviews=[Review(author="a" * 100, rating=5, text="y" * 500, when="w" * 100) for _ in range(5)])
    c = card_builder.build_card(d, "restaurant", [], [0], "high", "exif")
    blob = c.model_dump_json()
    assert len(blob.encode()) < 4096
    assert "1.234" not in blob and "5.678" not in blob and "lat" not in json.loads(blob)


def test_summary_fallback_uses_only_known_facts():
    c = card_builder.build_card(_details(), "restaurant", [], [0], "medium", "vision")
    assert c.summary == "Restaurant in Colaba, Mumbai."
    assert c.area == "Colaba, Mumbai"


def test_category_from_types():
    f = card_builder.category_from_types
    assert f(["restaurant", "food"], "restaurant") == "restaurant"
    assert f(["indian_restaurant"], "indian_restaurant") == "restaurant"
    assert f(["tourist_attraction", "point_of_interest"], None) == "landmark"
    assert f(["park"], "park") == "park"
    assert f(["cafe", "food"], "coffee_shop") == "cafe"
    assert f(["hardware_store"], None) == "other"


# ---- cache ----

def test_cache_ttl_expiry():
    t = [0.0]
    c = TTLCache(10, clock=lambda: t[0])
    c.set("a", 1)
    assert c.get("a") == 1
    t[0] = 11
    assert c.get("a") is None
    assert c.hits == 1 and c.misses == 1


# ---- exif ----

def test_exif_gps_extraction_roundtrip():
    from PIL import Image as I
    img = I.new("RGB", (8, 8))
    exif = img.getexif()
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (18.0, 55.0, 22.0)
    gps[3], gps[4] = "E", (72.0, 49.0, 55.0)
    data = make_jpeg(exif=exif)
    lat, lng = extract_gps(data)
    assert lat == pytest.approx(18 + 55 / 60 + 22 / 3600)
    assert lng == pytest.approx(72 + 49 / 60 + 55 / 3600)


def test_exif_southern_western_hemisphere():
    img = Image.new("RGB", (8, 8))
    exif = img.getexif()
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "S", (33.0, 0.0, 0.0)
    gps[3], gps[4] = "W", (70.0, 0.0, 0.0)
    lat, lng = extract_gps(make_jpeg(exif=exif))
    assert lat == pytest.approx(-33) and lng == pytest.approx(-70)


def test_exif_absent_or_garbage_returns_none():
    assert extract_gps(make_jpeg()) is None
    assert extract_gps(b"not an image") is None


# ---- google places parsing + request shape (offline via MockTransport; NOT a live check) ----

GOOGLE_DETAILS = {
    "id": "ChIJabc", "displayName": {"text": "Leopold Cafe"},
    "formattedAddress": "Colaba, Mumbai, India", "location": {"latitude": 18.9, "longitude": 72.8},
    "rating": 4.1, "userRatingCount": 100, "priceLevel": "PRICE_LEVEL_MODERATE",
    "types": ["restaurant"], "primaryType": "restaurant", "utcOffsetMinutes": 330,
    "currentOpeningHours": {"openNow": True},
    "regularOpeningHours": {"weekdayDescriptions": [f"Day{i}: 9-5" for i in range(7)]},
    "websiteUri": "https://x.example", "googleMapsUri": "https://maps.google.com/?cid=1",
    "editorialSummary": {"text": "Nice."},
    "reviews": [{"authorAttribution": {"displayName": "Ann"}, "rating": 5,
                 "text": {"text": "Great"}, "relativePublishTimeDescription": "a week ago"},
                {"authorAttribution": {"displayName": "Empty"}, "rating": 1, "text": {"text": ""}}],
}


def test_parse_details():
    d = parse_details(GOOGLE_DETAILS)
    assert d.name == "Leopold Cafe" and d.price_level == 2 and d.open_now is True
    assert d.hours_today and d.hours_today.startswith("Day")
    assert len(d.reviews) == 1 and d.reviews[0].author == "Ann"
    assert d.editorial_summary == "Nice."


def test_places_client_sends_key_and_field_mask():
    seen = {}

    def handler(request: httpx.Request):
        seen["headers"] = request.headers
        seen["url"] = str(request.url)
        return httpx.Response(200, json=GOOGLE_DETAILS)

    client = PlacesClient("KEY123", transport=httpx.MockTransport(handler))
    d = run(client.get_details("ChIJabc"))
    assert d.place_id == "ChIJabc"
    assert seen["headers"]["x-goog-api-key"] == "KEY123"
    assert seen["headers"]["x-goog-fieldmask"] == DETAILS_MASK
    assert seen["url"].endswith("/v1/places/ChIJabc")


def test_places_client_nearby_request_and_distance_sort():
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content)
        seen["mask"] = request.headers["x-goog-fieldmask"]
        return httpx.Response(200, json={"places": [
            {"id": "far", "displayName": {"text": "Far"}, "location": {"latitude": 18.9010, "longitude": 72.8000},
             "types": ["establishment"]},
            {"id": "near", "displayName": {"text": "Near"}, "location": {"latitude": 18.90001, "longitude": 72.8},
             "types": ["establishment"]},
        ]})

    client = PlacesClient("K", transport=httpx.MockTransport(handler))
    out = run(client.search_nearby(18.9, 72.8, 75))
    assert [p.place_id for p in out] == ["near", "far"]
    assert seen["body"]["locationRestriction"]["circle"]["radius"] == 75.0
    assert seen["body"]["rankPreference"] == "DISTANCE"
    assert "reviews" not in seen["mask"] and "rating" not in seen["mask"]  # cheap fields only


def test_places_client_http_error_does_not_leak_key():
    client = PlacesClient("SECRETKEY", transport=httpx.MockTransport(lambda r: httpx.Response(403, json={})))
    with pytest.raises(PlacesError) as e:
        run(client.search_text("x"))
    assert "SECRETKEY" not in str(e.value)


def test_places_client_details_404_returns_none_and_rejects_bad_ids():
    client = PlacesClient("K", transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert run(client.get_details("ChIJmissing")) is None
    assert run(client.get_details("../../evil")) is None


def test_haversine():
    assert haversine_m(0, 0, 0, 0) == 0
    assert 110_000 < haversine_m(0, 0, 1, 0) < 112_500


# ---- vision parsing + client behaviour (offline via MockTransport; NOT a live check) ----

def test_parse_vision_json_tolerates_fences_and_prose():
    raw = 'Sure!\n```json\n{"identifiable": true, "place_name": "Leopold Cafe", "confidence": "high", "evidence": ["sign"]}\n```'
    v = parse_vision_json(raw)
    assert v.identifiable and v.place_name == "Leopold Cafe" and v.confidence == "high"


def test_parse_vision_requires_evidence_to_name_a_place():
    v = parse_vision_json('{"identifiable": true, "place_name": "X", "confidence": "high", "evidence": []}')
    assert not v.identifiable and v.place_name is None


def test_parse_vision_garbage_raises():
    with pytest.raises(ValueError):
        parse_vision_json("I cannot help")


def _anthropic_reply(text):
    return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})


def test_anthropic_vision_request_shape_and_retry():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(529, json={})
        return _anthropic_reply('{"identifiable": false, "confidence": "low", "evidence": []}')

    v = AnthropicVision("K", "claude-sonnet-5-5", transport=httpx.MockTransport(handler))
    res = run(v.analyze(make_jpeg(), "Mumbai"))
    assert res.identifiable is False
    assert len(calls) == 2  # one retry
    body = json.loads(calls[1].content)
    assert body["model"] == "claude-sonnet-5-5"
    assert calls[1].headers["x-api-key"] == "K"
    block = body["messages"][0]["content"][0]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/jpeg"


def test_anthropic_vision_raises_after_retry():
    v = AnthropicVision("K", "m", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(VisionError):
        run(v.analyze(make_jpeg()))


def test_gemini_vision_request_shape_and_retry():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={})
        text = '{"identifiable": true, "place_name": "Leopold Cafe", "confidence": "high", "evidence": ["sign"]}'
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    v = GeminiVision("GK", "gemini-test-model", transport=httpx.MockTransport(handler))
    res = run(v.analyze(make_jpeg(), "Mumbai"))
    assert res.identifiable and res.place_name == "Leopold Cafe"
    assert len(calls) == 2  # one retry
    req = calls[1]
    assert req.url.path.endswith("/models/gemini-test-model:generateContent")
    assert req.headers["x-goog-api-key"] == "GK" and "key=" not in str(req.url)  # key in header, not URL
    body = json.loads(req.content)
    parts = body["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/jpeg" and parts[0]["inline_data"]["data"]
    assert body["generationConfig"]["response_mime_type"] == "application/json"
    assert "system_instruction" in body


def test_gemini_vision_raises_after_retry_and_on_empty_candidates():
    v = GeminiVision("K", "m", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(VisionError):
        run(v.analyze(make_jpeg()))
    v2 = GeminiVision("K", "m", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"candidates": []})))
    with pytest.raises(VisionError):
        run(v2.analyze(make_jpeg()))  # blocked/empty reply -> ValueError -> retried -> VisionError


# ---- Routes client (offline via MockTransport; NOT a live check) ----

def test_routes_client_matrix_request_shape_parsing_and_cache():
    from datetime import datetime, timezone
    from app.services.routes import RoutesClient
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={})
        return httpx.Response(200, json=[
            {"originIndex": 0, "destinationIndex": 1, "duration": "1500s", "staticDuration": "1000s",
             "distanceMeters": 6200, "condition": "ROUTE_EXISTS"},
            {"originIndex": 1, "destinationIndex": 0, "condition": "ROUTE_NOT_FOUND"},
        ])

    cache = TTLCache(60)
    c = RoutesClient("K", transport=httpx.MockTransport(handler), cache=cache)
    when = datetime(2026, 10, 17, 8, 0, tzinfo=timezone.utc)
    m = run(c.matrix([(1.0, 2.0), (1.1, 2.1)], "DRIVE", when))
    assert len(calls) == 2  # one retry after 503
    req = calls[1]
    assert req.headers["x-goog-api-key"] == "K" and "staticDuration" in req.headers["x-goog-fieldmask"]
    body = json.loads(req.content)
    assert body["travelMode"] == "DRIVE" and body["routingPreference"] == "TRAFFIC_AWARE"
    assert body["departureTime"] == "2026-10-17T08:00:00Z"
    assert "key=" not in str(req.url)
    assert (m[0][1].distance_m, m[0][1].duration_s, m[0][1].static_s) == (6200, 1500, 1000)
    assert m[1][0] is None and m[0][0].distance_m == 0
    run(c.matrix([(1.0, 2.0), (1.1, 2.1)], "DRIVE", when))  # 0->1 cached, 1->0 not cached -> still one more call
    assert len(calls) == 3


def test_routes_client_route_no_routes_is_none_and_transit_has_no_routing_preference():
    from datetime import datetime, timezone
    from app.services.routes import RoutesClient
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={})

    c = RoutesClient("K", transport=httpx.MockTransport(handler))
    when = datetime(2026, 10, 17, 8, 0, tzinfo=timezone.utc)
    assert run(c.route((1, 2), (1.1, 2.1), "TRANSIT", when)) is None  # no coverage -> "not available"
    assert seen[0]["travelMode"] == "TRANSIT" and "routingPreference" not in seen[0]
