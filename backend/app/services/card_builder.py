import re
from typing import Optional

from ..schemas import Card, NearbyItem, PlaceDetails, Review

SUMMARY_MAX = 200
REVIEW_MAX = 160
MAX_REVIEWS = 3
MAX_NEARBY = 3

PRICE_LABELS = {0: "Free", 1: "₹", 2: "₹₹", 3: "₹₹₹", 4: "₹₹₹₹"}

_CAFE = {"cafe", "coffee_shop"}
_RESTAURANT = {"restaurant", "food", "meal_takeaway", "meal_delivery", "bar", "bakery"}
_PARK = {"park", "national_park", "state_park", "playground", "garden"}
_LANDMARK = {
    "tourist_attraction", "museum", "place_of_worship", "hindu_temple", "church", "mosque",
    "synagogue", "monument", "landmark", "historical_landmark", "art_gallery", "stadium",
    "amusement_park", "natural_feature", "castle", "cultural_landmark", "historical_place",
}

CATEGORY_LABELS = {
    "restaurant": "Restaurant", "cafe": "Cafe", "park": "Park",
    "landmark": "Landmark", "other": "Place",
}


def truncate(text: Optional[str], limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def price_label(level: Optional[int]) -> Optional[str]:
    if level is None:
        return None
    return PRICE_LABELS.get(level)


def category_from_types(types: list[str], primary_type: Optional[str] = None) -> str:
    ordered = ([primary_type] if primary_type else []) + [t for t in types if t != primary_type]
    for t in ordered:
        if t in _CAFE or t.endswith("coffee_shop"):
            return "cafe"
        if t.endswith("restaurant") or t in {"restaurant", "meal_takeaway", "meal_delivery", "bar", "bakery"}:
            return "restaurant"
        if t in _PARK:
            return "park"
        if t in _LANDMARK:
            return "landmark"
    if "food" in types:
        return "restaurant"
    return "other"


def area_from_address(address: str) -> str:
    """Best-effort 'neighbourhood, city' from a formatted address (drops country and state/postcode)."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if len(parts) > 1:
        parts = parts[:-1]  # country
    if len(parts) > 1 and any(ch.isdigit() for ch in parts[-1]):
        parts = parts[:-1]  # "State 400001"
    return ", ".join(parts[-2:])


def make_summary(details: PlaceDetails, category: str, area: str) -> str:
    """editorialSummary if present; else one sentence built only from data we actually have."""
    if details.editorial_summary:
        return truncate(details.editorial_summary, SUMMARY_MAX)
    label = CATEGORY_LABELS.get(category, "Place")
    sentence = f"{label} in {area}." if area else f"{label}."
    return truncate(sentence, SUMMARY_MAX)


def build_card(
    details: PlaceDetails,
    category: str,
    nearby: list[NearbyItem],
    photo_indexes: list[int],
    confidence: str,
    source: str,
) -> Card:
    area = area_from_address(details.address)
    reviews = [
        Review(author=truncate(r.author, 40) or "Google user", rating=r.rating,
               text=truncate(r.text, REVIEW_MAX), when=truncate(r.when, 40))
        for r in details.reviews if r.text.strip()
    ][:MAX_REVIEWS]
    return Card(
        place_id=details.place_id,
        name=truncate(details.name, 100),
        category=category,
        is_restaurant=(category == "restaurant"),
        summary=make_summary(details, category, area),
        address=truncate(details.address, 160),
        area=area,
        rating=details.rating,
        rating_count=details.rating_count,
        price_level=details.price_level,
        price_label=price_label(details.price_level),
        open_now=details.open_now,
        hours_today=truncate(details.hours_today, 80) or None,
        reviews=reviews,
        nearby=nearby[:MAX_NEARBY],
        website=details.website,
        maps_url=details.maps_url,
        photo_indexes=sorted(set(photo_indexes)),
        confidence=confidence,
        source=source,
        attribution="Google Maps",
    )
