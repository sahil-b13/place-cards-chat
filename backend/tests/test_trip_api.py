import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

FIVE = ["mock_gateway_of_india", "mock_csmt", "mock_marine_drive", "mock_haji_ali", "mock_siddhivinayak"]


@pytest.fixture
def client():
    return TestClient(create_app(Settings(mock_mode=True)))


def test_trip_plan_happy_path_contract(client):
    r = client.post("/api/trip-plan", json={
        "place_ids": FIVE, "photo_indexes_by_place": {"mock_csmt": [0, 2]}, "start_time": "08:00",
        "start": {"text": "Colaba, Mumbai"}, "travelers": 2, "objective": "least_time",
        "variants": ["cheapest", "comfort"], "entry_fees": {"mock_csmt": 100}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and [p["plan_type"] for p in body["plans"]] == ["cheapest", "comfort"]
    p = body["plans"][1]
    assert set(p) >= {"version", "plan_type", "date", "start_time", "start_label", "travelers", "objective", "days",
                      "traffic_windows", "mode_options", "cost", "tips", "warnings", "attribution"}
    assert p["attribution"] == "Google Maps" and p["cost"]["is_estimate"] is True and p["cost"]["entry"] == 200
    stop = p["days"][0]["stops"][0]
    assert set(stop) >= {"order", "place_id", "name", "category", "arrive", "depart", "visit_minutes",
                         "photo_indexes", "maps_url", "leg_from_previous"}
    assert set(stop["leg_from_previous"]) == {"mode", "distance_km", "duration_min", "duration_in_traffic_min"}
    assert set(p["traffic_windows"][0]) == {"label", "from", "to", "level", "note"}  # "from" alias is serialized
    csmt = next(s for d in p["days"] for s in d["stops"] if s["place_id"] == "mock_csmt")
    assert csmt["photo_indexes"] == [0, 2]
    assert len(p["tips"]) <= 4 and len(p["warnings"]) <= 5


def test_unsupported_cross_city(client):
    r = client.post("/api/trip-plan", json={"place_ids": ["mock_madras_matunga", "mock_madras_pune"]})
    assert r.status_code == 200 and r.json()["status"] == "unsupported" and r.json()["plans"] == []


@pytest.mark.parametrize("payload", [
    {"place_ids": []},
    {"place_ids": [str(i) for i in range(11)]},
    {"place_ids": ["a"], "start_time": "25:00"},
    {"place_ids": ["a"], "start_time": "8:00"},
    {"place_ids": ["a"], "travelers": 0},
    {"place_ids": ["a"], "travelers": 21},
    {"place_ids": ["a"], "objective": "cheapest"},
    {"place_ids": ["a"], "variants": []},
    {"place_ids": ["a"], "date": "tomorrow"},
])
def test_validation_errors_422(client, payload):
    r = client.post("/api/trip-plan", json=payload)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_unknown_places_404_and_bad_date_400(client):
    r = client.post("/api/trip-plan", json={"place_ids": ["nope"]})
    assert r.status_code == 404 and r.json()["error"]["code"] == "places_not_found"
    r = client.post("/api/trip-plan", json={"place_ids": FIVE[:2], "date": "2020-01-01"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_date"
