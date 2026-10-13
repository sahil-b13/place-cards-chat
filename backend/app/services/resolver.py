"""Resolution logic (PROJECT_PLAN.md Section 5).

Per photo: EXIF/client GPS -> nearby search (+ vision in parallel) -> vision-only text search -> not_found.
Privacy: sender coordinates are only used for lookups; they never appear in any output model.
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz

from ..schemas import (Candidate, NearbyItem, PlaceDetails, PlaceResult, PlaceSummary,
                       ResolveRequest, ResolveResponse, VisionResult)
from . import exif as exif_service
from .card_builder import build_card, category_from_types
from .cache import TTLCache
from .places import is_poi

log = logging.getLogger("placecards.resolver")

NEARBY_RADIUS_M = 75
SINGLE_POI_RADIUS_M = 30
FUZZY_MIN = 70
STRONG_MATCH = 90
LANDMARK_NEARBY_RADIUS_M = 500
MIN_NEARBY_RATING_COUNT = 20
MAX_CANDIDATES = 5
CONCURRENCY = 4


@dataclass
class PhotoInput:
    index: int
    data: bytes
    lat: Optional[float] = None
    lng: Optional[float] = None
    hint: Optional[str] = None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).strip()


def ratio(a: str, b: str) -> float:
    return fuzz.ratio(_norm(a), _norm(b))


def lenient_ratio(a: str, b: str) -> float:
    """For sender-typed queries: also accept token subsets ('leopold' -> 'Leopold Cafe')."""
    return max(ratio(a, b), fuzz.token_set_ratio(_norm(a), _norm(b)))


def _area_matches(area_text: Optional[str], address: str) -> bool:
    tokens = [t for t in re.split(r"[^a-z0-9]+", (area_text or "").lower()) if len(t) >= 3]
    addr = (address or "").lower()
    return any(t in addr for t in tokens)


def _to_candidates(items: list[PlaceSummary]) -> list[Candidate]:
    seen, out = set(), []
    for c in items:
        if c.place_id and c.place_id not in seen:
            seen.add(c.place_id)
            out.append(Candidate(place_id=c.place_id, name=c.name, address=c.address))
    return out[:MAX_CANDIDATES]


def _valid_coords(lat, lng) -> bool:
    return (lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180
            and not (lat == 0 and lng == 0))


def choose_text_match(name: str, cands: list[PlaceSummary], area_text: Optional[str],
                      scorer=ratio) -> Optional[PlaceSummary]:
    """Accept the top search result only if it fuzzy-matches `name` and is not ambiguous.

    Ambiguous = two or more distinct results match the name strongly and nothing in the
    area/hint narrows it down to the top result."""
    if not cands:
        return None
    top = cands[0]
    if scorer(name, top.name) < FUZZY_MIN:
        return None
    strong = [c for c in cands if scorer(name, c.name) >= STRONG_MATCH]
    if len(strong) >= 2 and not _area_matches(area_text, top.address):
        return None
    return top


class Resolver:
    def __init__(self, places, vision, cache: TTLCache):
        self.places = places
        self.vision = vision
        self.cache = cache

    # ---------- public API ----------

    async def resolve_photos(self, photos: list[PhotoInput], global_hint: Optional[str] = None) -> list[PlaceResult]:
        sem = asyncio.Semaphore(CONCURRENCY)

        async def run(p: PhotoInput) -> PlaceResult:
            async with sem:
                try:
                    return await self._resolve_one(p, global_hint)
                except Exception:
                    # graceful partial results: one bad photo must not sink the batch
                    log.exception("photo %s failed", p.index)
                    return PlaceResult(photo_indexes=[p.index], status="not_found")

        singles = await asyncio.gather(*(run(p) for p in photos))
        return merge_results(list(singles))

    async def resolve_query(self, req: ResolveRequest) -> ResolveResponse:
        """Sender correction: free-text query or an explicit place_id pick. Card source is 'user'."""
        if req.place_id:
            details = await self._details(req.place_id)
            if details is None:
                return ResolveResponse(status="not_found")
            card = await self._card(details, [], "high", "user")
            return ResolveResponse(status="ok", card=card)

        query = (req.query or "").strip()
        q = f"{query} {req.hint}".strip() if req.hint else query
        lat, lng = (req.lat, req.lng) if _valid_coords(req.lat, req.lng) else (None, None)
        cands = await self.places.search_text(q, lat, lng, max_results=MAX_CANDIDATES)
        if not cands:
            return ResolveResponse(status="not_found")
        top = choose_text_match(query, cands, req.hint, scorer=lenient_ratio)
        if top is None:
            return ResolveResponse(status="low_confidence", candidates=_to_candidates(cands))
        details = await self._details(top.place_id)
        if details is None:
            return ResolveResponse(status="not_found")
        return ResolveResponse(status="ok", card=await self._card(details, [], "high", "user"))

    # ---------- per-photo flow ----------

    async def _safe_vision(self, p: PhotoInput, hint: Optional[str]) -> VisionResult:
        try:
            return await self.vision.analyze(p.data, hint, p.index)
        except Exception as e:
            log.warning("vision unavailable for photo %s: %s", p.index, type(e).__name__)
            return VisionResult()

    async def _resolve_one(self, p: PhotoInput, global_hint: Optional[str]) -> PlaceResult:
        hint = p.hint or global_hint
        lat, lng = p.lat, p.lng
        if not _valid_coords(lat, lng):
            lat, lng = None, None
            gps = exif_service.extract_gps(p.data)  # server-side fallback
            if gps and _valid_coords(*gps):
                lat, lng = gps
        has_gps = lat is not None

        pois: list[PlaceSummary] = []
        if has_gps:
            nearby, vis = await asyncio.gather(
                self.places.search_nearby(lat, lng, NEARBY_RADIUS_M),
                self._safe_vision(p, hint),
            )
            pois = [c for c in nearby if is_poi(c)]
        else:
            vis = await self._safe_vision(p, hint)

        vision_name = (vis.place_name if vis.identifiable and vis.place_name
                       and vis.confidence in ("high", "medium") else None)

        if has_gps:
            # Privacy guardrail: no public POI at this point and nothing readable in the photo
            # -> likely a private location. Return not_found, never an address.
            if not pois and not vision_name:
                return PlaceResult(photo_indexes=[p.index], status="not_found")
            if pois and vision_name:
                best = max(pois, key=lambda c: ratio(vision_name, c.name))
                if ratio(vision_name, best.name) >= FUZZY_MIN:
                    return await self._ok(best.place_id, p.index, "high", "exif")
                # vision named something that is not nearby (e.g. a landmark seen from afar): try text search
            elif pois:
                close = [c for c in pois if c.distance_m is not None and c.distance_m <= SINGLE_POI_RADIUS_M]
                if len(close) == 1:
                    return await self._ok(close[0].place_id, p.index, "medium", "exif")
                return PlaceResult(photo_indexes=[p.index], status="low_confidence",
                                   candidates=_to_candidates(pois))

        if vision_name:
            area_text = hint or vis.area_guess
            query = f"{vision_name} {area_text}".strip() if area_text else vision_name
            cands = await self.places.search_text(query, lat, lng, max_results=MAX_CANDIDATES)
            if cands:
                top = choose_text_match(vision_name, cands, area_text)
                if top is not None:
                    return await self._ok(top.place_id, p.index, "medium", "vision")
                ranked = sorted(cands, key=lambda c: -ratio(vision_name, c.name))
                return PlaceResult(photo_indexes=[p.index], status="low_confidence",
                                   candidates=_to_candidates(pois + ranked))

        if pois:  # GPS had POIs but vision gave nothing usable
            return PlaceResult(photo_indexes=[p.index], status="low_confidence",
                               candidates=_to_candidates(pois))
        return PlaceResult(photo_indexes=[p.index], status="not_found")

    # ---------- helpers ----------

    async def _ok(self, place_id: str, index: int, confidence: str, source: str) -> PlaceResult:
        details = await self._details(place_id)
        if details is None:
            return PlaceResult(photo_indexes=[index], status="not_found")
        card = await self._card(details, [index], confidence, source)
        return PlaceResult(photo_indexes=[index], status="ok", card=card)

    async def _details(self, place_id: str) -> Optional[PlaceDetails]:
        key = f"details:{place_id}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        details = await self.places.get_details(place_id)
        if details is not None:
            self.cache.set(key, details)
        return details

    async def _card(self, details: PlaceDetails, photo_indexes: list[int], confidence: str, source: str):
        category = category_from_types(details.types, details.primary_type)
        nearby: list[NearbyItem] = []
        if category in ("landmark", "park"):
            nearby = await self._nearby_restaurants(details)
        return build_card(details, category, nearby, photo_indexes, confidence, source)

    async def _nearby_restaurants(self, details: PlaceDetails) -> list[NearbyItem]:
        """Up to 3 rating-ranked restaurants within ~500 m of the VENUE (not the sender)."""
        if details.lat is None or details.lng is None:
            return []
        key = f"nearby:{details.place_id}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        try:
            found = await self.places.search_nearby(
                details.lat, details.lng, LANDMARK_NEARBY_RADIUS_M,
                included_types=["restaurant"], rank="POPULARITY", max_results=20, include_rating=True)
        except Exception as e:
            log.warning("nearby restaurants failed: %s", type(e).__name__)
            return []  # optional section; do not cache failures
        rated = [c for c in found
                 if c.place_id != details.place_id and c.rating is not None
                 and (c.rating_count is None or c.rating_count >= MIN_NEARBY_RATING_COUNT)]
        rated.sort(key=lambda c: -c.rating)
        items = [NearbyItem(name=c.name, rating=c.rating, distance_m=c.distance_m) for c in rated[:3]]
        self.cache.set(key, items)
        return items


_CONF_RANK = {"low": 0, "medium": 1, "high": 2}


def merge_results(results: list[PlaceResult]) -> list[PlaceResult]:
    """Photos that resolve to the same place_id become one result with all photo_indexes."""
    out: list[PlaceResult] = []
    by_pid: dict[str, PlaceResult] = {}
    for r in sorted(results, key=lambda r: min(r.photo_indexes)):
        if r.card is not None:
            pid = r.card.place_id
            existing = by_pid.get(pid)
            if existing is not None:
                merged = sorted(set(existing.photo_indexes) | set(r.photo_indexes))
                existing.photo_indexes = merged
                existing.card.photo_indexes = list(merged)
                if _CONF_RANK[r.card.confidence] > _CONF_RANK[existing.card.confidence]:
                    existing.card.confidence = r.card.confidence
                    existing.card.source = r.card.source
                continue
            by_pid[pid] = r
        out.append(r)
    return out
