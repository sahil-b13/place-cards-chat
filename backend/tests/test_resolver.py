import asyncio

from app.schemas import ResolveRequest
from app.services.resolver import PhotoInput
from app.services.vision import parse_scenarios

from tests.conftest import make_jpeg

LEOPOLD = (18.92298, 72.83187)
BETWEEN_LEOPOLD_MONDEGAR = (18.92306, 72.832135)
PRIVATE_SPOT = (19.2, 72.9)


def run(coro):
    return asyncio.run(coro)


def photo(i, lat=None, lng=None, hint=None):
    return PhotoInput(index=i, data=make_jpeg(), lat=lat, lng=lng, hint=hint)


def one(resolver, p, scenario="generic", **kw):
    """Resolve a single photo under an explicit mock vision scenario (never a filename)."""
    resolver.vision.scenarios = parse_scenarios(scenario)
    results = run(resolver.resolve_photos([p], **kw))
    assert len(results) == 1
    return results[0]


def test_exif_gps_plus_vision_match_is_ok_high(resolver):
    r = one(resolver, photo(0, *LEOPOLD), scenario="leopold")
    assert r.status == "ok"
    assert r.card.place_id == "mock_leopold_cafe"
    assert r.card.source == "exif" and r.card.confidence == "high"


def test_exif_gps_no_vision_single_poi_within_30m_is_medium(resolver):
    r = one(resolver, photo(0, *LEOPOLD), scenario="generic")
    assert r.status == "ok"
    assert r.card.place_id == "mock_leopold_cafe"
    assert r.card.source == "exif" and r.card.confidence == "medium"


def test_exif_gps_no_vision_two_pois_is_low_confidence_with_candidates(resolver):
    r = one(resolver, photo(0, *BETWEEN_LEOPOLD_MONDEGAR), scenario="generic")
    assert r.status == "low_confidence"
    assert r.card is None
    assert {c.place_id for c in r.candidates} == {"mock_leopold_cafe", "mock_cafe_mondegar"}


def test_vision_only_unique_match_is_ok_medium(resolver):
    r = one(resolver, photo(0), scenario="leopold")
    assert r.status == "ok"
    assert r.card.place_id == "mock_leopold_cafe"
    assert r.card.source == "vision" and r.card.confidence == "medium"


def test_vision_only_landmark_has_capped_ranked_nearby_restaurants(resolver):
    r = one(resolver, photo(0), scenario="gateway")
    c = r.card
    assert c.category == "landmark" and not c.is_restaurant
    assert len(c.nearby) == 3  # 4 restaurants in range, capped at 3
    assert [n.name for n in c.nearby] == ["Cafe Mondegar", "Leopold Cafe", "Bademiya"]
    assert all(n.distance_m is not None and n.distance_m <= 500 for n in c.nearby)


def test_restaurant_card_has_no_nearby(resolver):
    r = one(resolver, photo(0), scenario="leopold")
    assert r.card.is_restaurant and r.card.nearby == []


def test_ambiguous_vision_name_is_low_confidence(resolver):
    r = one(resolver, photo(0), scenario="ambiguous")
    assert r.status == "low_confidence"
    assert r.card is None
    assert len(r.candidates) == 3


def test_ambiguous_resolved_by_hint(resolver):
    r = one(resolver, photo(0, hint="Matunga, Mumbai"), scenario="ambiguous")
    assert r.status == "ok"
    assert r.card.place_id == "mock_madras_matunga"


def test_global_hint_applies(resolver):
    r = one(resolver, photo(0), scenario="ambiguous", global_hint="Matunga")
    assert r.status == "ok" and r.card.place_id == "mock_madras_matunga"


def test_neither_gps_nor_vision_is_not_found(resolver):
    r = one(resolver, photo(0), scenario="generic")
    assert r.status == "not_found" and r.card is None and r.candidates == []


def test_privacy_guardrail_gps_without_poi_is_not_found(resolver):
    r = one(resolver, photo(0, *PRIVATE_SPOT), scenario="generic")
    assert r.status == "not_found"
    assert r.card is None and r.candidates == []
    dumped = r.model_dump_json()
    assert "19.2" not in dumped and "72.9" not in dumped


def test_sender_coordinates_never_appear_in_output(resolver):
    r = one(resolver, photo(0, *LEOPOLD), scenario="leopold")
    dumped = r.model_dump_json()
    for needle in ("18.92298", "72.83187", '"lat"', '"lng"', "latitude", "longitude"):
        assert needle not in dumped


def test_gps_with_vision_naming_distant_landmark_falls_back_to_text_search(resolver):
    # standing ~150-200 m from the Gateway, photo of the Gateway: not within 75 m, vision still resolves it
    r = one(resolver, photo(0, 18.9226, 72.8336), scenario="gateway")
    assert r.status == "ok"
    assert r.card.place_id == "mock_gateway_of_india"


def test_dedupe_merges_photos_of_same_place(resolver):
    resolver.vision.scenarios = ["leopold", "gateway", "leopold"]  # by photo order
    photos = [photo(0), photo(1), photo(2, *LEOPOLD)]
    results = run(resolver.resolve_photos(photos))
    assert len(results) == 2
    leopold = next(r for r in results if r.card.place_id == "mock_leopold_cafe")
    assert leopold.photo_indexes == [0, 2]
    assert leopold.card.photo_indexes == [0, 2]
    assert leopold.card.confidence == "high"  # best confidence of the merged photos wins


def test_not_found_photos_are_not_merged(resolver):
    resolver.vision.scenarios = ["generic"]
    results = run(resolver.resolve_photos([photo(0), photo(1)]))
    assert [r.photo_indexes for r in results] == [[0], [1]]


def test_vision_failure_degrades_gracefully(resolver):
    class Boom:
        async def analyze(self, *a, **k):
            raise RuntimeError("down")
    resolver.vision = Boom()
    r = one(resolver, photo(0, *LEOPOLD), scenario="leopold")
    assert r.status == "ok" and r.card.confidence == "medium"  # GPS-only path still works


def test_details_are_cached_by_place_id(resolver):
    resolver.vision.scenarios = ["leopold"]
    run(resolver.resolve_photos([photo(0)]))
    hits_before = resolver.cache.hits
    run(resolver.resolve_photos([photo(0)]))
    assert resolver.cache.hits > hits_before


def test_concurrency_many_photos(resolver):
    resolver.vision.scenarios = ["gateway", "leopold"]  # alternates by photo order
    photos = [photo(i) for i in range(10)]
    results = run(resolver.resolve_photos(photos))
    assert sorted(i for r in results for i in r.photo_indexes) == list(range(10))
    assert len(results) == 2


# ---- /resolve logic ----

def test_resolve_by_place_id_sets_source_user(resolver):
    res = run(resolver.resolve_query(ResolveRequest(place_id="mock_gateway_of_india")))
    assert res.status == "ok" and res.card.source == "user" and res.card.confidence == "high"
    assert res.card.nearby


def test_resolve_by_query(resolver):
    res = run(resolver.resolve_query(ResolveRequest(query="Cafe Leopold", hint="Mumbai")))
    assert res.status == "ok" and res.card.place_id == "mock_leopold_cafe" and res.card.source == "user"


def test_resolve_ambiguous_query_returns_candidates(resolver):
    res = run(resolver.resolve_query(ResolveRequest(query="Cafe Madras")))
    assert res.status == "low_confidence" and len(res.candidates) == 3


def test_resolve_unknown_query_not_found(resolver):
    res = run(resolver.resolve_query(ResolveRequest(query="zzzz qqqq")))
    assert res.status == "not_found"


def test_resolve_unknown_place_id_not_found(resolver):
    assert run(resolver.resolve_query(ResolveRequest(place_id="nope"))).status == "not_found"


# ---- mock vision independence from filename / image bytes ----

def test_mock_vision_depends_only_on_scenario_and_order():
    from app.main import FIXTURES_DIR
    from app.services.vision import MockVision
    v = MockVision(FIXTURES_DIR, "")
    seq = [run(v.analyze(b"x", None, i)).place_name for i in range(5)]
    assert seq == ["Leopold Cafe", "Gateway of India", seq[2], None, "Leopold Cafe"]
    same_a = run(v.analyze(b"AAAA", None, 1))
    same_b = run(v.analyze(b"completely different bytes", None, 1))
    assert same_a == same_b  # image content is never inspected


def test_mock_scenario_setting_single_and_list():
    from app.main import FIXTURES_DIR
    from app.services.vision import MockVision
    assert run(MockVision(FIXTURES_DIR, "gateway").analyze(b"", None, 3)).place_name == "Gateway of India"
    v = MockVision(FIXTURES_DIR, "generic, leopold")
    assert [run(v.analyze(b"", None, i)).identifiable for i in range(4)] == [False, True, False, True]


def test_unknown_mock_scenario_is_an_error():
    import pytest
    with pytest.raises(ValueError):
        parse_scenarios("leopold,nonsense")
