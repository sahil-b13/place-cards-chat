import glob
import json
import logging
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from rapidfuzz import fuzz

from ..schemas import PlaceDetails, PlaceSummary, Review

log = logging.getLogger("placecards.places")

BASE_URL = "https://places.googleapis.com/v1"

# Search results: cheap identity fields only. Rated variant is used for the "nearby restaurants" call.
SEARCH_MASK = "places.id,places.displayName,places.formattedAddress,places.location,places.types,places.primaryType"
SEARCH_MASK_RATED = SEARCH_MASK + ",places.rating,places.userRatingCount"
# Details (higher-cost fields): fetched only for the final chosen place, then cached.
DETAILS_MASK = (
    "id,displayName,formattedAddress,location,rating,userRatingCount,priceLevel,reviews,"
    "regularOpeningHours,currentOpeningHours,websiteUri,googleMapsUri,editorialSummary,"
    "types,primaryType,utcOffsetMinutes"
)

PRICE_ENUM = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}

# Results that are addresses/regions rather than public points of interest.
_POI_TYPES = {"establishment", "point_of_interest", "tourist_attraction", "park", "natural_feature"}


def is_poi(p: PlaceSummary) -> bool:
    """True for named public places; False for streets, addresses, localities, premises."""
    return bool(set(p.types) & _POI_TYPES)


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class PlacesError(Exception):
    pass


# ---------- parsing helpers (Google Places API (New) JSON -> our models) ----------

def _display_name(p: dict) -> str:
    return (p.get("displayName") or {}).get("text") or ""


def parse_summary(p: dict, origin: Optional[tuple[float, float]] = None) -> PlaceSummary:
    loc = p.get("location") or {}
    lat, lng = loc.get("latitude"), loc.get("longitude")
    dist = None
    if origin and lat is not None and lng is not None:
        dist = round(haversine_m(origin[0], origin[1], lat, lng))
    return PlaceSummary(
        place_id=p.get("id", ""),
        name=_display_name(p),
        address=p.get("formattedAddress", ""),
        lat=lat, lng=lng, distance_m=dist,
        types=list(p.get("types") or []),
        primary_type=p.get("primaryType"),
        rating=p.get("rating"),
        rating_count=p.get("userRatingCount"),
    )


def _hours_today(p: dict) -> Optional[str]:
    desc = (p.get("regularOpeningHours") or {}).get("weekdayDescriptions") or []
    if len(desc) != 7:
        return None
    offset = p.get("utcOffsetMinutes")
    now = datetime.now(timezone.utc)
    if isinstance(offset, int):
        now = now + timedelta(minutes=offset)
    return desc[now.weekday()]  # Google lists Monday first, like Python's weekday()


def parse_details(p: dict) -> PlaceDetails:
    loc = p.get("location") or {}
    reviews = []
    for r in p.get("reviews") or []:
        text = ((r.get("text") or r.get("originalText") or {}).get("text")) or ""
        if not text.strip():
            continue
        reviews.append(Review(
            author=(r.get("authorAttribution") or {}).get("displayName") or "Google user",
            rating=r.get("rating"),
            text=text,
            when=r.get("relativePublishTimeDescription", ""),
        ))
    open_now = (p.get("currentOpeningHours") or {}).get("openNow")
    if open_now is None:
        open_now = (p.get("regularOpeningHours") or {}).get("openNow")
    return PlaceDetails(
        place_id=p.get("id", ""),
        name=_display_name(p),
        address=p.get("formattedAddress", ""),
        lat=loc.get("latitude"), lng=loc.get("longitude"),
        types=list(p.get("types") or []),
        primary_type=p.get("primaryType"),
        rating=p.get("rating"),
        rating_count=p.get("userRatingCount"),
        price_level=PRICE_ENUM.get(p.get("priceLevel", "")),
        open_now=open_now,
        hours_today=_hours_today(p),
        reviews=reviews,
        website=p.get("websiteUri"),
        maps_url=p.get("googleMapsUri", ""),
        editorial_summary=(p.get("editorialSummary") or {}).get("text"),
        weekday_hours=[str(x) for x in ((p.get("regularOpeningHours") or {}).get("weekdayDescriptions") or [])][:7]
        if len((p.get("regularOpeningHours") or {}).get("weekdayDescriptions") or []) == 7 else [],
        utc_offset_minutes=p.get("utcOffsetMinutes") if isinstance(p.get("utcOffsetMinutes"), int) else None,
    )


# ---------- real client ----------

class PlacesClient:
    def __init__(self, api_key: str, timeout: float = 10.0,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        self.api_key = api_key
        self.timeout = timeout
        self._transport = transport

    async def _request(self, method: str, path: str, mask: str, body: Optional[dict] = None):
        headers = {"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": mask,
                   "Content-Type": "application/json"}
        what = path.split("/")[1].split(":")[-1]
        last: Optional[str] = None
        for attempt in range(2):  # one retry on transient errors (timeouts, network, 429/5xx)
            try:
                async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                    resp = await client.request(method, f"{BASE_URL}{path}", headers=headers, json=body)
            except httpx.HTTPError as e:
                last = type(e).__name__
                log.warning("places %s attempt %d failed: %s", what, attempt + 1, last)
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                log.warning("places %s attempt 1 got http %d, retrying", what, resp.status_code)
                last = f"http {resp.status_code}"
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                # never include the key or coordinates in errors
                raise PlacesError(f"places http {resp.status_code} on {what}")
            return resp.json()
        raise PlacesError(f"places request failed on {what}: {last}")

    async def search_text(self, query: str, lat: Optional[float] = None, lng: Optional[float] = None,
                          max_results: int = 5) -> list[PlaceSummary]:
        body: dict = {"textQuery": query, "pageSize": max(1, min(max_results, 20))}
        origin = None
        if lat is not None and lng is not None:
            origin = (lat, lng)
            body["locationBias"] = {"circle": {
                "center": {"latitude": lat, "longitude": lng}, "radius": 2000.0}}
        data = await self._request("POST", "/places:searchText", SEARCH_MASK, body) or {}
        return [parse_summary(p, origin) for p in data.get("places", [])]

    async def search_nearby(self, lat: float, lng: float, radius_m: float,
                            included_types: Optional[list[str]] = None, rank: str = "DISTANCE",
                            max_results: int = 20, include_rating: bool = False) -> list[PlaceSummary]:
        body: dict = {
            "locationRestriction": {"circle": {
                "center": {"latitude": lat, "longitude": lng}, "radius": float(radius_m)}},
            "maxResultCount": max(1, min(max_results, 20)),
            "rankPreference": rank,
        }
        if included_types:
            body["includedTypes"] = included_types
        mask = SEARCH_MASK_RATED if include_rating else SEARCH_MASK
        data = await self._request("POST", "/places:searchNearby", mask, body) or {}
        out = [parse_summary(p, (lat, lng)) for p in data.get("places", [])]
        if rank == "DISTANCE":
            out.sort(key=lambda s: s.distance_m if s.distance_m is not None else 10**9)
        return out

    async def get_details(self, place_id: str) -> Optional[PlaceDetails]:
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,300}", place_id or ""):
            return None
        data = await self._request("GET", f"/places/{place_id}", DETAILS_MASK)
        return parse_details(data) if data else None


# ---------- mock client ----------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).strip()


class MockPlaces:
    """Fixture-driven stand-in for PlacesClient. Loads fixtures/places_*.json (key: "places")."""

    def __init__(self, fixtures_dir: str):
        self.places: dict[str, PlaceDetails] = {}
        for path in sorted(glob.glob(os.path.join(fixtures_dir, "places_*.json"))):
            with open(path, encoding="utf-8") as f:
                for rec in json.load(f).get("places", []):
                    d = PlaceDetails(**rec)
                    if not d.weekday_hours and d.hours_today and ":" in d.hours_today:
                        # sample data only states one day; repeat its hours for every weekday
                        text = d.hours_today.split(":", 1)[1].strip()
                        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                        d.weekday_hours = [f"{x}: {text}" for x in days]
                    self.places[d.place_id] = d

    @staticmethod
    def _summary(d: PlaceDetails, origin=None) -> PlaceSummary:
        dist = None
        if origin and d.lat is not None and d.lng is not None:
            dist = round(haversine_m(origin[0], origin[1], d.lat, d.lng))
        return PlaceSummary(place_id=d.place_id, name=d.name, address=d.address, lat=d.lat, lng=d.lng,
                            distance_m=dist, types=d.types, primary_type=d.primary_type,
                            rating=d.rating, rating_count=d.rating_count)

    async def search_text(self, query, lat=None, lng=None, max_results=5):
        q = _norm(query)
        scored = []
        for d in self.places.values():
            s = fuzz.token_set_ratio(q, _norm(f"{d.name} {d.address}"))
            if s >= 60:
                scored.append((s, d))
        scored.sort(key=lambda t: -t[0])  # stable: fixture order breaks ties
        origin = (lat, lng) if lat is not None and lng is not None else None
        return [self._summary(d, origin) for _, d in scored[:max_results]]

    async def search_nearby(self, lat, lng, radius_m, included_types=None, rank="DISTANCE",
                            max_results=20, include_rating=False):
        out = []
        for d in self.places.values():
            if d.lat is None or d.lng is None:
                continue
            if haversine_m(lat, lng, d.lat, d.lng) > radius_m:
                continue
            if included_types and not (set(included_types) & set(d.types)):
                continue
            out.append(self._summary(d, (lat, lng)))
        if rank == "DISTANCE":
            out.sort(key=lambda s: s.distance_m)
        else:
            out.sort(key=lambda s: -(s.rating_count or 0))
        return out[:max_results]

    async def get_details(self, place_id):
        return self.places.get(place_id)
