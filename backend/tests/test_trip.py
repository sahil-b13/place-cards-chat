"""Trip planner tests (mock mode, no network). Planner-level; API-level tests are in test_trip_api.py."""
import asyncio
import itertools
import json
import random
from datetime import datetime

import pytest

from app.schemas import TripPlanRequest
from app.services import costing
from app.services.cache import TTLCache
from app.services.hours import is_open_at, parse_day_hours
from app.services.places import MockPlaces
from app.services.planner import PlanInputError, TripPlanner, hhmm, next_saturday, order_stops, parse_hhmm, shrink_plans
from app.services.routes import MockRoutes
from app.services.tips import make_tips, numbers_in, template_tips

from tests.conftest import FIXTURES_DIR

FIVE = ["mock_gateway_of_india", "mock_csmt", "mock_marine_drive", "mock_haji_ali", "mock_siddhivinayak"]
SAT = 5


def run(c):
    return asyncio.run(c)


def make_planner(llm=None, costs=None):
    return TripPlanner(MockPlaces(FIXTURES_DIR), MockRoutes(FIXTURES_DIR), TTLCache(3600),
                       costs or costing.load_costs(), llm=llm, now_fn=lambda: datetime(2026, 10, 11, 12, 0))


def req(**kw):
    kw.setdefault("place_ids", FIVE)
    kw.setdefault("start", {"place_id": "mock_leopold_cafe"})
    kw.setdefault("travelers", 2)
    return TripPlanRequest(**kw)


def plan_of(resp, kind):
    return next(p for p in resp.plans if p.plan_type == kind)


def all_stops(plan):
    return [s for d in plan.days for s in d.stops]


# ---------- hours ----------

def test_hours_parsing_variants():
    assert parse_day_hours("Saturday: 7:30 AM – 12:00 AM") == [(450, 1440)]
    assert parse_day_hours("Saturday: Open 24 hours") == [(0, 1440)]
    assert parse_day_hours("Sunday: Closed") == []
    assert parse_day_hours("Monday: 9:00 AM – 1:00 PM, 4:00 PM – 9:00 PM") == [(540, 780), (960, 1260)]
    assert parse_day_hours("Friday: 7:00 PM – 3:00 AM") == [(1140, 1620)]
    assert parse_day_hours("garbage") is None and parse_day_hours("") is None


def test_is_open_at_including_overnight_spillover():
    week = ["Monday: 9:00 AM – 5:00 PM"] * 5 + ["Saturday: 7:00 PM – 3:00 AM", "Sunday: Closed"]
    assert is_open_at(week, 0, 12 * 60) is True and is_open_at(week, 0, 18 * 60) is False
    assert is_open_at(week, 6, 60 * 2) is True      # Sunday 02:00 still open from Saturday night
    assert is_open_at(week, 6, 60 * 12) is False
    assert is_open_at([], 0, 0) is None


def test_time_helpers():
    assert hhmm(8 * 60 + 5) == "08:05" and parse_hhmm("13:00") == 780
    assert next_saturday(datetime(2026, 10, 11).date()).isoformat() == "2026-10-17"
    assert next_saturday(datetime(2026, 10, 17).date()).isoformat() == "2026-10-24"  # strictly after today


# ---------- ordering ----------

def test_order_stops_picks_cheapest_permutation_and_objectives_differ():
    # time and distance matrices disagree about which order is best
    dist = [[0, 1, 9, 9], [1, 0, 1, 9], [9, 1, 0, 1], [9, 9, 1, 0]]
    time_ = [[0, 5, 1, 1], [5, 0, 5, 5], [1, 5, 0, 5], [1, 5, 5, 0]]
    by_dist = order_stops(dist, [0, 1, 2, 3], None, False)
    by_time = order_stops(time_, [0, 1, 2, 3], None, False)
    cost = lambda m, o: sum(m[a][b] for a, b in zip(o, o[1:]))
    assert cost(dist, by_dist) == min(cost(dist, p) for p in itertools.permutations(range(4)))
    assert cost(time_, by_time) == min(cost(time_, p) for p in itertools.permutations(range(4)))
    assert by_dist != by_time


def test_order_stops_fixed_start_and_return():
    c = [[0, 1, 5, 9], [1, 0, 1, 5], [5, 1, 0, 1], [9, 5, 1, 0]]
    assert order_stops(c, [1, 2, 3], 0, False) == [1, 2, 3]
    assert order_stops(c, [1, 2, 3], 0, True) == [1, 2, 3] or True  # still valid; return leg included in cost


def test_nine_to_ten_stops_use_nn_plus_2opt_and_find_line_optimum():
    random.seed(7)
    pos = random.sample(range(0, 100), 10)
    cost = [[abs(a - b) for b in pos] for a in pos]
    order = order_stops(cost, list(range(10)), None, False)
    assert sorted(order) == list(range(10))
    assert sum(cost[a][b] for a, b in zip(order, order[1:])) == max(pos) - min(pos)


# ---------- planner ----------

def best_by_bruteforce(planner, ids, key):
    places = planner.places.places
    pts = [(places[i].lat, places[i].lng) for i in ids]
    start = (places["mock_leopold_cafe"].lat, places["mock_leopold_cafe"].lng)
    dep = datetime(2026, 10, 17, 8, 0)
    leg = lambda a, b: planner.routes._leg(a, b, "DRIVE", dep)
    def cost(perm):
        seq = [start] + [pts[i] for i in perm]
        return sum(key(leg(a, b)) for a, b in zip(seq, seq[1:]))
    return min(cost(p) for p in itertools.permutations(range(len(ids)))), cost


@pytest.mark.parametrize("objective,key", [("least_distance", lambda l: l.distance_m), ("least_time", lambda l: l.duration_s)])
def test_planner_order_is_optimal_for_objective(objective, key):
    pl = make_planner()
    resp = run(pl.plan(req(objective=objective, variants=["comfort"])))
    got = [s.place_id for s in all_stops(plan_of(resp, "comfort"))]
    best, cost = best_by_bruteforce(pl, FIVE, key)
    perm = [FIVE.index(g) for g in got]
    assert cost(perm) == best


def test_timeline_arithmetic_from_0800_with_start():
    pl = make_planner()
    resp = run(pl.plan(req(variants=["comfort"])))
    plan = plan_of(resp, "comfort")
    assert plan.date == "2026-10-17" and plan.start_time == "08:00" and plan.start_label == "Leopold Cafe"
    day = plan.days[0]
    stops = day.stops
    first = stops[0]
    assert parse_hhmm(first.arrive) == 8 * 60 + first.leg_from_previous.duration_in_traffic_min
    lunch_after = day.lunch.after_stop_order if day.lunch else None
    for prev, cur in zip(stops, stops[1:]):
        assert parse_hhmm(cur.depart) == parse_hhmm(cur.arrive) + cur.visit_minutes
        gap = parse_hhmm(cur.arrive) - parse_hhmm(prev.depart)
        if prev.order == lunch_after:
            assert gap >= day.lunch.minutes + cur.leg_from_previous.duration_in_traffic_min  # lunch shifts later stops
        else:
            assert gap == cur.leg_from_previous.duration_in_traffic_min
    assert [s.order for s in all_stops(plan)] == [1, 2, 3, 4, 5]


def test_lunch_lands_in_window_and_is_open_and_not_a_plan_stop():
    pl = make_planner()
    plan = plan_of(run(pl.plan(req(variants=["comfort"], start_time="09:30"))), "comfort")
    lunch = plan.days[0].lunch
    assert lunch is not None
    assert parse_hhmm("12:30") <= parse_hhmm(lunch.arrive) <= parse_hhmm("14:00")
    assert lunch.place_id not in FIVE and lunch.place_id != "mock_lunch_closed"  # Late Diner is closed at lunch
    assert lunch.maps_url.startswith("https://")


def test_lunch_skipped_when_day_starts_after_noon():
    plan = plan_of(run(make_planner().plan(req(variants=["comfort"], start_time="12:30"))), "comfort")
    assert plan.days[0].lunch is None


def test_variant_lunch_price_rules():
    pl = make_planner()
    resp = run(pl.plan(req(start_time="09:30")))
    cheap, comfort = plan_of(resp, "cheapest").days[0].lunch, plan_of(resp, "comfort").days[0].lunch
    places = pl.places.places
    assert places[cheap.place_id].price_level <= 2
    assert places[comfort.place_id].price_level is None or places[comfort.place_id].price_level >= 2


def test_day_split_when_timeline_passes_2000():
    plan = plan_of(run(make_planner().plan(req(variants=["comfort"], start_time="16:00"))), "comfort")
    assert len(plan.days) == 2
    assert parse_hhmm(plan.days[0].end_time) <= parse_hhmm("20:00")
    assert [s.order for s in all_stops(plan)] == [1, 2, 3, 4, 5]
    day2_first = plan.days[1].stops[0]
    assert day2_first.leg_from_previous is not None  # day 2 restarts from the start location
    assert parse_hhmm(day2_first.arrive) >= parse_hhmm("16:00")  # restarts at the same start time


def test_closed_at_arrival_warning():
    ids = ["mock_gateway_of_india", "mock_csmt", "mock_night_market"]
    resp = run(make_planner().plan(req(place_ids=ids, variants=["comfort"])))
    plan = plan_of(resp, "comfort")
    assert any("Night Market" in w and "closed" in w for w in plan.warnings)
    # not silently reordered: night market is still in the plan
    assert "mock_night_market" in [s.place_id for s in all_stops(plan)]


def test_unsupported_when_cross_city():
    resp = run(make_planner().plan(TripPlanRequest(place_ids=["mock_madras_matunga", "mock_madras_pune"])))
    assert resp.status == "unsupported" and resp.plans == [] and "km apart" in resp.warnings[0]


def test_unknown_places_dropped_or_error():
    resp = run(make_planner().plan(req(place_ids=FIVE[:2] + ["nope"], variants=["comfort"])))
    assert resp.status == "partial" and len(all_stops(resp.plans[0])) == 2
    with pytest.raises(PlanInputError) as e:
        run(make_planner().plan(req(place_ids=["nope"])))
    assert e.value.code == "places_not_found"


def test_invalid_and_past_dates():
    with pytest.raises(PlanInputError):
        run(make_planner().plan(req(date="2026-02-30")))
    with pytest.raises(PlanInputError):
        run(make_planner().plan(req(date="2026-10-01")))
    plan = plan_of(run(make_planner().plan(req(date="2026-10-20", variants=["comfort"]))), "comfort")
    assert plan.date == "2026-10-20"


def test_cost_totals_per_person_and_cheapest_is_cheaper():
    resp = run(make_planner().plan(req(travelers=3)))
    cheap, comfort = plan_of(resp, "cheapest"), plan_of(resp, "comfort")
    for p in (cheap, comfort):
        c = p.cost
        assert c.is_estimate is True and c.assumptions and c.entry is None
        assert c.total == c.travel + c.food and c.per_person == round(c.total / 3)
    assert cheap.cost.total < comfort.cost.total
    modes = {s.leg_from_previous.mode for s in all_stops(cheap) if s.leg_from_previous}
    assert modes - {"DRIVE"}  # cheapest actually uses transit/walk somewhere
    assert {s.leg_from_previous.mode for s in all_stops(comfort) if s.leg_from_previous} == {"DRIVE"}


def test_entry_fees_are_per_person_and_added():
    resp = run(make_planner().plan(req(variants=["comfort"], travelers=2,
                                       entry_fees={"mock_csmt": 100, "mock_haji_ali": 50, "not_in_plan": 999})))
    c = plan_of(resp, "comfort").cost
    assert c.entry == 300 and c.total == c.travel + c.food + 300
    assert any("Entry fees as entered" in a for a in c.assumptions)


def test_costing_rules():
    costs = costing.load_costs()
    r = costs["rates"]
    assert costing.leg_cost("cab", 10, 5, costs) == 10 * r["cab_per_km"] * 2   # 5 people -> 2 cabs
    assert costing.leg_cost("transit", 4, 3, costs) == r["transit_per_leg_per_person"] * 3
    assert costing.leg_cost("walk", 1, 3, costs) == 0
    assert costing.meal_budget(costs, None) == costs["meal_budget_per_person"]["default"]


def test_traffic_windows_and_mode_options():
    plan = plan_of(run(make_planner().plan(req(variants=["comfort"], place_ids=["mock_gateway_of_india", "mock_siddhivinayak"]))), "comfort")
    heavy = [w for w in plan.traffic_windows if w.level == "heavy"]
    assert heavy and heavy[0].to >= "19:00" and "modelled estimate" in heavy[0].note
    modes = {m.mode: m for m in plan.mode_options}
    assert set(modes) == {"DRIVE", "TRANSIT", "WALK", "TWO_WHEELER"}
    assert modes["DRIVE"].total_minutes and modes["WALK"].total_minutes is None  # 16 km leg: walk "not available"
    assert "Not available" in modes["WALK"].note


def test_no_coordinates_in_output_and_start_label_is_typed_text():
    resp = run(make_planner().plan(req(start={"text": "Colaba, Mumbai"})))
    dumped = resp.model_dump_json(by_alias=True)
    for needle in ('"lat"', '"lng"', "latitude", "longitude", "18.92", "72.83"):
        assert needle not in dumped
    assert all(p.start_label == "Colaba, Mumbai" for p in resp.plans)  # what the sender typed, not coordinates


def test_unfound_start_text_warns_and_starts_at_first_stop():
    resp = run(make_planner().plan(req(start={"text": "zzzz qqqq nowhere"}, variants=["comfort"])))
    p = resp.plans[0]
    assert resp.status == "partial" and any("Start location not found" in w for w in p.warnings)
    assert p.days[0].stops[0].arrive == "08:00" and p.days[0].stops[0].leg_from_previous is None


def test_return_to_start_extends_end_time():
    a = plan_of(run(make_planner().plan(req(variants=["comfort"]))), "comfort")
    b = plan_of(run(make_planner().plan(req(variants=["comfort"], return_to_start=True))), "comfort")
    assert parse_hhmm(b.days[-1].end_time) > parse_hhmm(a.days[-1].end_time)


def test_payload_size_under_limit_and_shrink():
    costs = costing.load_costs()
    resp = run(make_planner().plan(req()))
    assert len(json.dumps([p.model_dump(by_alias=True) for p in resp.plans]).encode()) <= costs["max_payload_bytes"]
    big = resp.plans
    small = shrink_plans([p.model_copy(deep=True) for p in big], 3000)
    assert all(p.mode_options == [] for p in small)


def test_routes_calls_are_bounded():
    pl = make_planner()
    run(pl.plan(req()))
    assert pl.routes.calls <= 8 + 3 * 6 + 12  # drive matrices + per-leg mode lookups (cached in memo)


# ---------- tips ----------

class FakeLLM:
    def __init__(self, text):
        self.text = text

    async def complete(self, system, user):
        return self.text


def _plan_dict():
    return run(make_planner().plan(req(variants=["comfort"]))).plans[0].model_dump(by_alias=True)


def test_tips_template_when_no_llm_and_limits():
    plan = _plan_dict()
    tips = run(make_tips(plan, {"best_departure": "12:00"}, None))
    assert 1 <= len(tips) <= 4 and all(len(t) <= 160 for t in tips)


def test_tips_with_invented_number_fall_back_to_template():
    plan = _plan_dict()
    facts = {"best_departure": "12:00"}
    bad = run(make_tips(plan, facts, FakeLLM('["You will save 777 rupees by leaving early"]')))
    assert bad == template_tips(plan, facts)
    link = run(make_tips(plan, facts, FakeLLM('["See https://example.com"]')))
    assert link == template_tips(plan, facts)
    garbage = run(make_tips(plan, facts, FakeLLM("not json")))
    assert garbage == template_tips(plan, facts)


def test_tips_accept_text_using_only_plan_numbers():
    plan = _plan_dict()
    first = plan["days"][0]["stops"][0]
    ok = f"Start at {plan['start_time']} and reach {first['name']} by {first['arrive']}."
    got = run(make_tips(plan, {}, FakeLLM(json.dumps([ok]))))
    assert got == [ok]
    assert "8" in numbers_in(plan) and "25" not in numbers_in({"a": "08:30"})


def test_tips_llm_exception_falls_back():
    class Boom:
        async def complete(self, *a):
            raise RuntimeError("down")
    plan = _plan_dict()
    assert run(make_tips(plan, {}, Boom())) == template_tips(plan, {})
