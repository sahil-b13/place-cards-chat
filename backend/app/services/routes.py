"""Google Routes API client (traffic-aware) + deterministic MockRoutes.

Both expose the same async interface:
  matrix(points, mode, depart) -> n x n list of Leg|None
  route(origin, dest, mode, depart) -> Leg|None
`points` are (lat, lng) tuples; `depart` is a tz-aware datetime. Coordinates stay server-side.
Version-sensitive request shapes follow the Routes API docs; NOT verified live from the build sandbox.
"""
import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from .places import haversine_m

log = logging.getLogger("placecards.routes")

MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
MATRIX_MASK = "originIndex,destinationIndex,duration,staticDuration,distanceMeters,condition"
ROUTES_MASK = "routes.duration,routes.staticDuration,routes.distanceMeters"
TRAFFIC_MODES = ("DRIVE", "TWO_WHEELER")


@dataclass(frozen=True)
class Leg:
    distance_m: int
    duration_s: int   # in traffic for DRIVE/TWO_WHEELER; plain for WALK/TRANSIT
    static_s: int     # free-flow duration


class RoutesError(Exception):
    pass


def _secs(v) -> Optional[int]:
    if isinstance(v, str) and v.endswith("s"):
        try:
            return int(round(float(v[:-1])))
        except ValueError:
            return None
    return None


def _wp(pt):
    return {"location": {"latLng": {"latitude": pt[0], "longitude": pt[1]}}}


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _leg_from(el: dict, mode: str) -> Optional[Leg]:
    dur = _secs(el.get("duration"))
    dist = el.get("distanceMeters")
    if dur is None or not isinstance(dist, (int, float)):
        return None
    st = _secs(el.get("staticDuration"))
    if st is None or mode not in TRAFFIC_MODES:
        st = dur
    return Leg(int(dist), dur, st)


class RoutesClient:
    def __init__(self, api_key: str, timeout: float = 15.0,
                 transport: Optional[httpx.AsyncBaseTransport] = None, cache=None):
        self.api_key = api_key
        self.timeout = timeout
        self._transport = transport
        self.cache = cache
        self.calls = 0  # Routes API requests made (cache hits excluded); logged per plan

    async def _post(self, url: str, mask: str, body: dict):
        headers = {"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": mask, "Content-Type": "application/json"}
        last = None
        for attempt in range(2):  # one retry on transient errors
            try:
                async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                    self.calls += 1
                    resp = await client.post(url, headers=headers, json=body)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    last = RoutesError(f"routes http {resp.status_code}")
                    continue
                if resp.status_code >= 400:
                    raise RoutesError(f"routes http {resp.status_code}")
                return resp.json()
            except httpx.HTTPError as e:
                last = e
        raise RoutesError(f"routes request failed: {type(last).__name__}")

    @staticmethod
    def _key(a, b, mode, depart: datetime) -> str:
        return f"route:{a[0]:.4f},{a[1]:.4f}>{b[0]:.4f},{b[1]:.4f}:{mode}:{depart.strftime('%Y%m%d%H')}"

    def _modes_body(self, mode: str, depart: datetime) -> dict:
        body = {"travelMode": mode, "departureTime": _rfc3339(depart)}
        if mode in TRAFFIC_MODES:
            body["routingPreference"] = "TRAFFIC_AWARE"
        return body

    async def matrix(self, points, mode, depart):
        n = len(points)
        out: list[list[Optional[Leg]]] = [[None] * n for _ in range(n)]
        todo = False
        for i in range(n):
            for j in range(n):
                if i == j:
                    out[i][j] = Leg(0, 0, 0)
                    continue
                c = self.cache.get(self._key(points[i], points[j], mode, depart)) if self.cache else None
                if c is not None:
                    out[i][j] = c
                else:
                    todo = True
        if not todo:
            return out
        body = {"origins": [{"waypoint": _wp(p)} for p in points],
                "destinations": [{"waypoint": _wp(p)} for p in points], **self._modes_body(mode, depart)}
        data = await self._post(MATRIX_URL, MATRIX_MASK, body)
        for el in data if isinstance(data, list) else []:
            i, j = el.get("originIndex"), el.get("destinationIndex")
            if not isinstance(i, int) or not isinstance(j, int) or i == j or not (0 <= i < n and 0 <= j < n):
                continue
            if el.get("condition") not in (None, "ROUTE_EXISTS"):
                continue
            leg = _leg_from(el, mode)
            if leg is not None:
                out[i][j] = leg
                if self.cache:
                    self.cache.set(self._key(points[i], points[j], mode, depart), leg)
        return out

    async def route(self, origin, dest, mode, depart):
        key = self._key(origin, dest, mode, depart)
        if self.cache:
            c = self.cache.get(key)
            if c is not None:
                return c
        body = {"origin": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}},
                "destination": {"location": {"latLng": {"latitude": dest[0], "longitude": dest[1]}}},
                **self._modes_body(mode, depart)}
        try:
            data = await self._post(ROUTES_URL, ROUTES_MASK, body)
        except RoutesError as e:
            log.warning("route %s failed: %s", mode, e)
            return None
        routes = (data or {}).get("routes") or []
        if not routes:
            return None  # e.g. no transit coverage: say "not available", never guess
        leg = _leg_from(routes[0], mode)
        if leg is not None and self.cache:
            self.cache.set(key, leg)
        return leg


class MockRoutes:
    """Deterministic stand-in: straight-line distance x road factor, fixed speeds, hour-of-day traffic."""

    def __init__(self, fixtures_dir: str):
        with open(os.path.join(fixtures_dir, "routes_mock.json"), encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.calls = 0

    def _mult(self, mode: str, depart: datetime) -> float:
        m = float(self.cfg["traffic_multiplier_by_hour"].get(str(depart.hour), 1.0))
        if mode == "DRIVE":
            return m
        if mode == "TWO_WHEELER":
            return 1 + (m - 1) * 0.6
        return 1.0

    def _leg(self, a, b, mode, depart) -> Optional[Leg]:
        if tuple(a) == tuple(b):
            return Leg(0, 0, 0)
        km = haversine_m(a[0], a[1], b[0], b[1]) / 1000 * self.cfg["road_factor"]
        if mode == "WALK" and km > self.cfg["walk_max_km"]:
            return None
        if mode == "TRANSIT" and km > self.cfg["transit_max_km"]:
            return None
        if mode not in self.cfg["speed_kmh"]:
            return None
        static_min = km / self.cfg["speed_kmh"][mode] * 60
        if mode == "TRANSIT":
            static_min += self.cfg["transit_wait_min"]
        total_min = static_min * self._mult(mode, depart)
        return Leg(int(round(km * 1000)), int(round(total_min * 60)), int(round(static_min * 60)))

    async def matrix(self, points, mode, depart):
        self.calls += 1
        return [[self._leg(a, b, mode, depart) for b in points] for a in points]

    async def route(self, origin, dest, mode, depart):
        self.calls += 1
        return self._leg(origin, dest, mode, depart)
