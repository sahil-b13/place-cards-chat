"""One-day trip planner (PROJECT_PLAN Section 5B).

Every number comes from the Routes/Places data or from costs.json assumptions, computed here.
The AI is only used (in tips.py) to phrase short tips from the finished plan.
"""
import asyncio
import itertools
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from ..schemas import (ModeOption, PlaceDetails, TrafficWindow, TripDay, TripLeg, TripLunch, TripPlan,
                       TripPlanRequest, TripPlanResponse, TripStop)
from . import costing
from .card_builder import category_from_types, price_label
from .hours import is_open_at
from .places import haversine_m
from .routes import Leg
from .tips import make_tips

log = logging.getLogger("placecards.planner")

MODES = ["DRIVE", "TRANSIT", "WALK", "TWO_WHEELER"]
BIG = 1e12
MAX_PERMUTATION_STOPS = 8
MAX_WARNINGS = 5


class PlanInputError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message


def hhmm(minutes: int) -> str:
    return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"


def parse_hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def next_saturday(today: date) -> date:
    return today + timedelta(days=((5 - today.weekday()) % 7) or 7)


# ---------------- ordering ----------------

def order_stops(cost: list[list[float]], stop_pts: list[int], start_idx: Optional[int], return_to_start: bool) -> list[int]:
    """Best visiting order of point indexes `stop_pts` under `cost`. Optimal for <= 8 stops, else NN + 2-opt."""

    def path_cost(order) -> float:
        c, prev = 0.0, start_idx
        for s in order:
            if prev is not None:
                c += cost[prev][s]
            prev = s
        if return_to_start and start_idx is not None and order:
            c += cost[prev][start_idx]
        return c

    if len(stop_pts) <= MAX_PERMUTATION_STOPS:
        return list(min(itertools.permutations(stop_pts), key=path_cost))

    def two_opt(order):
        order = list(order)
        improved = True
        while improved:
            improved = False
            for i in range(len(order) - 1):
                for j in range(i + 1, len(order)):
                    cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                    if path_cost(cand) < path_cost(order) - 1e-9:
                        order, improved = cand, True
        return order

    best = None
    firsts = [None] if start_idx is not None else stop_pts
    for first in firsts:
        if first is None:
            order, rem, cur = [], list(stop_pts), start_idx
        else:
            order, rem, cur = [first], [p for p in stop_pts if p != first], first
        while rem:
            nxt = min(rem, key=lambda r: cost[cur][r])
            order.append(nxt)
            rem.remove(nxt)
            cur = nxt
        order = two_opt(order)
        if best is None or path_cost(order) < path_cost(best):
            best = order
    return best


# ---------------- internal records ----------------

@dataclass
class StopInfo:
    place: PlaceDetails
    category: str
    visit_min: int
    photo_indexes: list[int]


@dataclass
class ChosenLeg:
    mode: str
    rate_kind: str       # cab | auto | transit | walk
    distance_m: int
    static_min: int
    traffic_min: int


@dataclass
class Ctx:
    req: TripPlanRequest
    stops: list[StopInfo]
    pts: list[tuple[float, float]]
    stop_pt: list[int]            # point index of each stop
    start_idx: Optional[int]
    start_label: str
    plan_date: date
    route_date: date
    offset_min: int
    start_min: int
    mats: dict[int, list[list[Optional[Leg]]]] = field(default_factory=dict)
    mode_memo: dict = field(default_factory=dict)
    entry_per_person: Optional[float] = None


@dataclass
class DayBuild:
    day: int
    rows: list            # (stop_idx, ChosenLeg|None, arrive, depart)
    lunch: Optional[dict]
    end_min: int
    return_leg: Optional[ChosenLeg]
    warnings: list[str]


def _tripleg(l: ChosenLeg) -> TripLeg:
    return TripLeg(mode=l.mode, distance_km=round(l.distance_m / 1000, 1),
                   duration_min=l.static_min, duration_in_traffic_min=l.traffic_min)


class TripPlanner:
    def __init__(self, places, routes, cache, costs: dict, llm=None, now_fn=None):
        self.places, self.routes, self.cache, self.costs, self.llm = places, routes, cache, costs, llm
        self.now = now_fn or datetime.now

    # ---------- data helpers ----------

    async def _details(self, pid: str) -> Optional[PlaceDetails]:
        key = f"details:{pid}"
        c = self.cache.get(key)
        if c is not None:
            return c
        d = await self.places.get_details(pid)
        if d is not None:
            self.cache.set(key, d)
        return d

    def _depart(self, ctx: Ctx, minute: int) -> datetime:
        tz = timezone(timedelta(minutes=ctx.offset_min))
        return datetime.combine(ctx.route_date, time(0), tz) + timedelta(minutes=minute)

    def _drive_leg(self, ctx: Ctx, p: int, q: int, minute: int) -> Optional[Leg]:
        key = min(ctx.mats, key=lambda m: abs(m - minute))
        return ctx.mats[key][p][q]

    async def _mode_leg(self, ctx: Ctx, p: int, q: int, mode: str) -> Optional[Leg]:
        if mode == "DRIVE":
            return self._drive_leg(ctx, p, q, ctx.start_min)
        k = (p, q, mode)
        if k not in ctx.mode_memo:
            ctx.mode_memo[k] = await self.routes.route(ctx.pts[p], ctx.pts[q], mode, self._depart(ctx, ctx.start_min))
        return ctx.mode_memo[k]

    @staticmethod
    def _chosen(mode: str, rate: str, leg: Leg) -> ChosenLeg:
        return ChosenLeg(mode, rate, leg.distance_m, round(leg.static_s / 60), round(leg.duration_s / 60))

    async def _choose_leg(self, ctx: Ctx, variant: str, p: int, q: int, minute: int) -> ChosenLeg:
        drive = self._drive_leg(ctx, p, q, minute)
        if variant == "cheapest":
            ch = self.costs["cheapest"]
            for mode, rate in (("WALK", "walk"), ("TRANSIT", "transit")):
                leg = await self._mode_leg(ctx, p, q, mode)
                if leg is None:
                    continue
                if mode == "WALK" and leg.distance_m / 1000 > ch["walk_max_km"]:
                    continue
                if drive is None or leg.duration_s <= ch["time_factor"] * drive.duration_s:
                    return self._chosen(mode, rate, leg)
            if drive is not None:
                return self._chosen("DRIVE", "auto", drive)
        elif drive is not None:
            return self._chosen("DRIVE", "cab", drive)
        for mode, rate in (("TRANSIT", "transit"), ("WALK", "walk")):  # last resort: any real route
            leg = await self._mode_leg(ctx, p, q, mode)
            if leg is not None:
                return self._chosen(mode, rate, leg)
        raise PlanInputError("no_route", "No route found between two of the places")

    # ---------- lunch ----------

    async def _pick_lunch(self, ctx: Ctx, stop: StopInfo, variant: str, depart_min: int, weekday: int, plan_ids: set):
        lc = self.costs["lunch"]
        found = await self.places.search_nearby(stop.place.lat, stop.place.lng, lc["radius_m"],
                                                included_types=["restaurant"], rank="POPULARITY",
                                                max_results=20, include_rating=True)
        rated = [c for c in found if c.place_id not in plan_ids and c.rating is not None
                 and (c.rating_count is None or c.rating_count >= lc["min_rating_count"])]
        rated.sort(key=lambda c: -c.rating)
        ok = []
        for c in rated[:6]:
            d = await self._details(c.place_id)
            if d is None:
                continue
            walk = max(3, round((c.distance_m if c.distance_m is not None else 400) / 80))
            if is_open_at(d.weekday_hours, weekday, (depart_min + walk) % 1440) is False:
                continue
            ok.append((d, c, walk))
        if variant == "cheapest":
            ok = [t for t in ok if t[0].price_level is None or t[0].price_level <= self.costs["cheapest"]["max_lunch_price_level"]]
        else:
            pref = [t for t in ok if t[0].price_level is not None and t[0].price_level >= self.costs["comfort"]["min_lunch_price_level"]]
            ok = pref or ok
        return ok[0] if ok else None

    # ---------- timeline ----------

    async def _run(self, ctx: Ctx, seq: list[int], variant: str, lunch_pos=None, lunch_walk=0, final_return=False):
        lc = self.costs["lunch"]
        clock, prev_pt, rows, lunch_arrive = ctx.start_min, ctx.start_idx, [], None
        for pos, si in enumerate(seq):
            pt = ctx.stop_pt[si]
            leg = await self._choose_leg(ctx, variant, prev_pt, pt, clock) if prev_pt is not None else None
            arrive = clock + (leg.traffic_min if leg else 0)
            depart = arrive + ctx.stops[si].visit_min
            rows.append((si, leg, arrive, depart))
            clock, prev_pt = depart, pt
            if lunch_pos == pos:
                lunch_arrive = clock + lunch_walk
                clock = lunch_arrive + lc["minutes"] + lunch_walk
        end, ret = rows[-1][3], None
        if final_return and ctx.start_idx is not None:
            ret = await self._choose_leg(ctx, variant, prev_pt, ctx.start_idx, end)
            end += ret.traffic_min
        return rows, lunch_arrive, end, ret

    async def _build_day(self, ctx: Ctx, seq: list[int], variant: str, day_idx: int, order_no: dict, final_return: bool) -> DayBuild:
        lc = self.costs["lunch"]
        weekday = (ctx.plan_date + timedelta(days=day_idx)).weekday()
        plan_ids = {s.place.place_id for s in ctx.stops}
        rows, _, end1, ret = await self._run(ctx, seq, variant, final_return=final_return)
        lunch, warnings = None, []
        last_depart = rows[-1][3]
        if ctx.start_min <= parse_hhmm("12:00") and last_depart >= parse_hhmm(lc["earliest"]):
            lo, hi = parse_hhmm(lc["earliest"]) - 60, parse_hhmm(lc["latest"]) + 60
            cands = [k for k in (range(len(seq)) if len(seq) == 1 else range(len(seq) - 1))
                     if lo <= rows[k][3] <= hi]
            if cands:
                k = min(cands, key=lambda k: abs(rows[k][3] - parse_hhmm(lc["target"])))
                stop = ctx.stops[seq[k]]
                pick = await self._pick_lunch(ctx, stop, variant, rows[k][3], weekday, plan_ids)
                if pick:
                    d, c, walk = pick
                    rows, lunch_arrive, end1, ret = await self._run(ctx, seq, variant, k, walk, final_return)
                    lunch = {"after": order_no[seq[k]], "details": d, "arrive": lunch_arrive}
                else:
                    warnings.append("No suitable open lunch place found near the route")
            else:
                warnings.append("No stop falls near lunchtime, so lunch was not scheduled")
        for si, _, arrive, _ in rows:
            p = ctx.stops[si].place
            if is_open_at(p.weekday_hours, weekday, arrive % 1440) is False:
                warnings.append(f"{p.name} may be closed when you arrive ({hhmm(arrive)})")
        return DayBuild(day_idx + 1, rows, lunch, end1, ret, warnings)

    async def _plan_variant(self, ctx: Ctx, order: list[int], variant: str) -> tuple[list[DayBuild], list[str]]:
        order_no = {si: i + 1 for i, si in enumerate(order)}
        day_end = parse_hhmm(self.costs["day_end"])
        remaining, builds, day_idx = list(order), [], 0
        while remaining:
            for m in range(len(remaining), 0, -1):
                last = m == len(remaining)
                b = await self._build_day(ctx, remaining[:m], variant, day_idx, order_no,
                                          final_return=ctx.req.return_to_start and last)
                if b.end_min <= day_end or m == 1:
                    break
            builds.append(b)
            remaining = remaining[m:]
            day_idx += 1
        return builds, [w for b in builds for w in b.warnings]

    # ---------- shared analysis ----------

    def _traffic(self, ctx: Ctx, order: list[int]):
        tc = self.costs["traffic"]
        pairs, prev = [], ctx.start_idx
        for si in order:
            if prev is not None:
                pairs.append((prev, ctx.stop_pt[si]))
            prev = ctx.stop_pt[si]
        ratios = {}
        for h in tc["slots"]:
            m = ctx.mats.get(h * 60)
            legs = [m[p][q] for p, q in pairs if m and m[p][q] is not None and m[p][q].static_s > 0]
            if legs:
                ratios[h] = sum(l.duration_s for l in legs) / sum(l.static_s for l in legs)
        level = lambda r: "heavy" if r >= tc["heavy_ratio"] else "moderate" if r >= tc["moderate_ratio"] else "light"
        windows, cur = [], None
        for h in sorted(ratios):
            lv = level(ratios[h])
            if cur and cur["level"] == lv and cur["to_h"] == h:
                cur["to_h"] = h + tc["slot_hours"]
                cur["peak"] = max(cur["peak"], ratios[h])
            else:
                cur = {"level": lv, "from_h": h, "to_h": h + tc["slot_hours"], "peak": ratios[h]}
                windows.append(cur)
        out = []
        for w in windows:
            if w["level"] == "light":
                continue
            label = "Morning traffic" if w["from_h"] < 12 else "Midday traffic" if w["from_h"] < 16 else "Evening rush"
            out.append(TrafficWindow(label=label, **{"from": f"{w['from_h']:02d}:00"}, to=f"{w['to_h'] % 24:02d}:00",
                                     level=w["level"], note=f"Drive times up to {w['peak']:.1f}x normal (modelled estimate)"))
        if not out and ratios:
            out.append(TrafficWindow(label="Light traffic", **{"from": f"{min(ratios):02d}:00"},
                                     to=f"{(max(ratios) + tc['slot_hours']) % 24:02d}:00", level="light",
                                     note="No heavy traffic modelled (estimate)"))
        facts = {}
        if ratios:
            lo = min(ratios, key=lambda h: (ratios[h], h))
            facts = {"best_departure": f"{lo:02d}:00", "best_departure_ratio": round(ratios[lo], 1)}
        return out, facts

    async def _mode_options(self, ctx: Ctx, order: list[int]) -> list[ModeOption]:
        pairs, prev = [], ctx.start_idx
        for si in order:
            if prev is not None:
                pairs.append((prev, ctx.stop_pt[si]))
            prev = ctx.stop_pt[si]
        if not pairs:
            return []
        out = []
        for mode in MODES:
            legs = await asyncio.gather(*[self._mode_leg(ctx, p, q, mode) for p, q in pairs])
            if any(l is None for l in legs):
                out.append(ModeOption(mode=mode, note="Not available for every leg"))
                continue
            out.append(ModeOption(mode=mode, total_minutes=sum(round(l.duration_s / 60) for l in legs),
                                  total_km=round(sum(l.distance_m for l in legs) / 1000, 1),
                                  note="Includes traffic" if mode in ("DRIVE", "TWO_WHEELER") else "Scheduled/typical time"))
        return out

    # ---------- main entry ----------

    async def plan(self, req: TripPlanRequest) -> TripPlanResponse:
        warnings: list[str] = []
        ids = list(dict.fromkeys(req.place_ids))
        details = await asyncio.gather(*[self._details(i) for i in ids])
        stops: list[StopInfo] = []
        for pid, d in zip(ids, details):
            if d is None or d.lat is None or d.lng is None:
                warnings.append("A selected place could not be found and was left out")
                continue
            cat = category_from_types(d.types, d.primary_type)
            stops.append(StopInfo(d, cat, int(self.costs["visit_minutes"].get(cat, self.costs["visit_minutes"]["other"])),
                                  list(req.photo_indexes_by_place.get(pid, []))))
        if not stops:
            raise PlanInputError("places_not_found", "None of the selected places could be found")
        warnings = list(dict.fromkeys(warnings))

        start_pt, start_label = None, ""
        if req.start and (req.start.place_id or (req.start.text and req.start.text.strip())):
            start_pt, start_label = await self._resolve_start(req, stops)
            if start_pt is None:
                warnings.append("Start location not found; the plan starts at the first stop")

        # scope check: one city/region only
        coords = [(s.place.lat, s.place.lng) for s in stops] + ([start_pt] if start_pt else [])
        far = max((haversine_m(a[0], a[1], b[0], b[1]) for a, b in itertools.combinations(coords, 2)), default=0) / 1000
        if far > self.costs["scope_km"]:
            return TripPlanResponse(plans=[], status="unsupported", warnings=[
                f"These places are about {round(far)} km apart. Trip plans cover one city or region "
                f"(up to {self.costs['scope_km']} km); flights and trains are not supported."])

        today = self.now().date()
        if req.date:
            try:
                plan_date = date.fromisoformat(req.date)
            except ValueError:
                raise PlanInputError("invalid_date", "date must be a real calendar date (YYYY-MM-DD)")
            if plan_date < today:
                raise PlanInputError("invalid_date", "date must be today or later")
        else:
            plan_date = next_saturday(today)
        route_date = plan_date
        while route_date <= today:  # traffic-aware routing needs a future departure; same weekday next week
            route_date += timedelta(days=7)

        off = stops[0].place.utc_offset_minutes
        ctx = Ctx(req=req, stops=stops, pts=([start_pt] if start_pt else []) + [(s.place.lat, s.place.lng) for s in stops],
                  stop_pt=[i + (1 if start_pt else 0) for i in range(len(stops))], start_idx=0 if start_pt else None,
                  start_label=start_label, plan_date=plan_date, route_date=route_date,
                  offset_min=off if off is not None else int(self.costs["timezone_offset_minutes"]),
                  start_min=parse_hhmm(req.start_time))
        fees = [req.entry_fees[s.place.place_id] for s in stops if s.place.place_id in req.entry_fees]
        ctx.entry_per_person = float(sum(fees)) if fees else None

        minutes = sorted({ctx.start_min} | {h * 60 for h in self.costs["traffic"]["slots"]})
        mats = await asyncio.gather(*[self.routes.matrix(ctx.pts, "DRIVE", self._depart(ctx, m)) for m in minutes])
        ctx.mats = dict(zip(minutes, mats))

        base = ctx.mats[ctx.start_min]
        pick = (lambda l: BIG if l is None else (l.duration_s if req.objective == "least_time" else l.distance_m))
        cost = [[pick(base[i][j]) if i != j else 0.0 for j in range(len(ctx.pts))] for i in range(len(ctx.pts))]
        order_pts = order_stops(cost, ctx.stop_pt, ctx.start_idx, req.return_to_start and ctx.start_idx is not None)
        order = [ctx.stop_pt.index(p) for p in order_pts]
        seq = ([ctx.start_idx] if ctx.start_idx is not None else []) + order_pts
        bad = any(cost[a][b] >= BIG for a, b in zip(seq, seq[1:]))
        if bad:
            return TripPlanResponse(plans=[], status="unsupported",
                                    warnings=["No driving route could be found between some of these places."])
        if req.return_to_start and ctx.start_idx is None:
            warnings.append("return_to_start needs a start location; ignored")

        windows, facts = self._traffic(ctx, order)
        modes = await self._mode_options(ctx, order)
        plans = []
        for variant in req.variants:
            builds, vwarn = await self._plan_variant(ctx, order, variant)
            plans.append(await self._assemble(ctx, variant, builds, vwarn + warnings, windows, modes, facts))
        plans = shrink_plans(plans, int(self.costs["max_payload_bytes"]))
        calls = getattr(self.routes, "calls", None)
        log.info("trip plan: %d stops, %d variants, routes api calls so far=%s", len(stops), len(plans), calls)
        status = "partial" if warnings else "ok"
        return TripPlanResponse(plans=plans, status=status, warnings=warnings[:MAX_WARNINGS])

    async def _resolve_start(self, req: TripPlanRequest, stops: list[StopInfo]):
        s = req.start
        if s.place_id:
            d = await self._details(s.place_id)
            if d and d.lat is not None and d.lng is not None:
                return (d.lat, d.lng), d.name
        text = (s.text or "").strip()
        if text:
            try:
                found = await self.places.search_text(text, lat=stops[0].place.lat, lng=stops[0].place.lng, max_results=1)
            except Exception as e:
                log.warning("start geocode failed: %s", type(e).__name__)
                found = []
            if found and found[0].lat is not None and found[0].lng is not None:
                return (found[0].lat, found[0].lng), text[:120]  # label = what the sender typed
        return None, ""

    async def _assemble(self, ctx: Ctx, variant: str, builds: list[DayBuild], warnings: list[str],
                        windows, modes, facts) -> TripPlan:
        days, legs_cost, lunch_levels = [], [], []
        order_no = {}
        for b in builds:
            for si, *_ in b.rows:
                order_no[si] = len(order_no) + 1
        for b in builds:
            stops_out = []
            for si, leg, arrive, depart in b.rows:
                st = ctx.stops[si]
                stops_out.append(TripStop(order=order_no[si], place_id=st.place.place_id, name=st.place.name,
                                          category=st.category, arrive=hhmm(arrive), depart=hhmm(depart),
                                          visit_minutes=st.visit_min, photo_indexes=st.photo_indexes,
                                          maps_url=st.place.maps_url or f"https://www.google.com/maps/search/?api=1&query={st.place.name.replace(' ', '+')}&query_place_id={st.place.place_id}",
                                          leg_from_previous=_tripleg(leg) if leg else None))
                if leg:
                    legs_cost.append((leg.rate_kind, leg.distance_m / 1000))
            if b.return_leg:
                legs_cost.append((b.return_leg.rate_kind, b.return_leg.distance_m / 1000))
            lunch = None
            if b.lunch:
                d = b.lunch["details"]
                lunch_levels.append(d.price_level)
                lunch = TripLunch(after_stop_order=b.lunch["after"], name=d.name, place_id=d.place_id,
                                  arrive=hhmm(b.lunch["arrive"]), minutes=int(self.costs["lunch"]["minutes"]),
                                  price_label=price_label(d.price_level), rating=d.rating,
                                  maps_url=d.maps_url or f"https://www.google.com/maps/search/?api=1&query={d.name.replace(' ', '+')}&query_place_id={d.place_id}")
            days.append(TripDay(day=b.day, stops=stops_out, lunch=lunch, end_time=hhmm(b.end_min)))
        cost = costing.estimate_cost(legs_cost, lunch_levels, ctx.entry_per_person, ctx.req.travelers, self.costs)
        plan = TripPlan(plan_type=variant, date=ctx.plan_date.isoformat(), start_time=ctx.req.start_time,
                        start_label=ctx.start_label, travelers=ctx.req.travelers, objective=ctx.req.objective,
                        days=days, traffic_windows=windows, mode_options=modes, cost=cost,
                        warnings=list(dict.fromkeys(warnings))[:MAX_WARNINGS])
        plan.tips = await make_tips(plan.model_dump(by_alias=True), facts, self.llm)
        return plan


def plans_size(plans: list[TripPlan]) -> int:
    return len(json.dumps([p.model_dump(by_alias=True) for p in plans], ensure_ascii=False, separators=(",", ":")).encode())


def shrink_plans(plans: list[TripPlan], max_bytes: int) -> list[TripPlan]:
    """Keep the serialized plans under max_bytes: drop mode_options first, then shorten notes, then tips."""
    if plans_size(plans) <= max_bytes:
        return plans
    for p in plans:
        p.mode_options = []
    if plans_size(plans) <= max_bytes:
        return plans
    for p in plans:
        for w in p.traffic_windows:
            w.note = w.note[:40]
        p.cost.assumptions = [a[:60] for a in p.cost.assumptions][:3]
        p.warnings = [w[:80] for w in p.warnings]
    if plans_size(plans) <= max_bytes:
        return plans
    for p in plans:
        p.tips = p.tips[:2]
    return plans
