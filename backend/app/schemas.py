from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["restaurant", "landmark", "cafe", "park", "other"]
Confidence = Literal["high", "medium", "low"]
Source = Literal["exif", "vision", "user"]
Status = Literal["ok", "low_confidence", "not_found"]


class Review(BaseModel):
    author: str
    rating: Optional[int] = None
    text: str
    when: str = ""


class NearbyItem(BaseModel):
    name: str
    rating: Optional[float] = None
    distance_m: Optional[int] = None


class Card(BaseModel):
    place_id: str
    name: str
    category: Category = "other"
    is_restaurant: bool = False
    summary: str = ""
    address: str = ""
    area: str = ""
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    price_level: Optional[int] = None
    price_label: Optional[str] = None
    open_now: Optional[bool] = None
    hours_today: Optional[str] = None
    reviews: list[Review] = Field(default_factory=list)
    nearby: list[NearbyItem] = Field(default_factory=list)
    website: Optional[str] = None
    maps_url: str = ""
    photo_indexes: list[int] = Field(default_factory=list)
    confidence: Confidence = "medium"
    source: Source = "vision"
    attribution: str = "Google Maps"


class Candidate(BaseModel):
    place_id: str
    name: str
    address: str = ""


class PlaceResult(BaseModel):
    photo_indexes: list[int]
    status: Status
    card: Optional[Card] = None
    candidates: list[Candidate] = Field(default_factory=list)


class PlaceCardsResponse(BaseModel):
    results: list[PlaceResult]


class ResolveRequest(BaseModel):
    query: Optional[str] = Field(default=None, max_length=200)
    place_id: Optional[str] = Field(default=None, max_length=300)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    hint: Optional[str] = Field(default=None, max_length=120)


class ResolveResponse(BaseModel):
    status: Status
    card: Optional[Card] = None
    candidates: list[Candidate] = Field(default_factory=list)


class PhotoMeta(BaseModel):
    index: int = Field(ge=0)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    hint: Optional[str] = Field(default=None, max_length=120)


class VisionResult(BaseModel):
    identifiable: bool = False
    place_name: Optional[str] = None
    place_type: Optional[str] = None
    area_guess: Optional[str] = None
    country_guess: Optional[str] = None
    confidence: Confidence = "low"
    evidence: list[str] = Field(default_factory=list)


class PlaceSummary(BaseModel):
    """Lightweight place record from search results (no reviews/hours)."""
    place_id: str
    name: str
    address: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    distance_m: Optional[int] = None
    types: list[str] = Field(default_factory=list)
    primary_type: Optional[str] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None


class PlaceDetails(BaseModel):
    """Full place record from Places details (higher-cost fields)."""
    place_id: str
    name: str
    address: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    types: list[str] = Field(default_factory=list)
    primary_type: Optional[str] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    price_level: Optional[int] = None
    open_now: Optional[bool] = None
    hours_today: Optional[str] = None
    reviews: list[Review] = Field(default_factory=list)
    website: Optional[str] = None
    maps_url: str = ""
    editorial_summary: Optional[str] = None
    weekday_hours: list[str] = Field(default_factory=list)  # 7 Google descriptions, Monday first
    utc_offset_minutes: Optional[int] = None


# ---------------- Trip planner (Section 4.7 / 4.8) ----------------

TripMode = Literal["DRIVE", "TRANSIT", "WALK", "TWO_WHEELER"]
PlanType = Literal["cheapest", "comfort"]
Objective = Literal["least_time", "least_distance"]
TIME_RE = r"^([01]\d|2[0-3]):[0-5]\d$"


class TripStartIn(BaseModel):
    text: Optional[str] = Field(default=None, max_length=120)  # typed text only, never raw GPS
    place_id: Optional[str] = Field(default=None, max_length=300)


class TripPlanRequest(BaseModel):
    place_ids: list[str] = Field(min_length=1, max_length=10)
    photo_indexes_by_place: dict[str, list[int]] = Field(default_factory=dict)
    start_time: str = Field(default="08:00", pattern=TIME_RE)
    date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    start: Optional[TripStartIn] = None
    return_to_start: bool = False
    travelers: int = Field(default=1, ge=1, le=20)
    objective: Objective = "least_time"
    variants: list[PlanType] = Field(default_factory=lambda: ["cheapest", "comfort"], min_length=1, max_length=2)
    entry_fees: dict[str, float] = Field(default_factory=dict)


class TripLeg(BaseModel):
    mode: TripMode
    distance_km: float
    duration_min: int
    duration_in_traffic_min: int


class TripStop(BaseModel):
    order: int
    place_id: str
    name: str
    category: str = "other"
    arrive: str
    depart: str
    visit_minutes: int
    photo_indexes: list[int] = Field(default_factory=list)
    maps_url: str = ""
    leg_from_previous: Optional[TripLeg] = None


class TripLunch(BaseModel):
    after_stop_order: int
    name: str
    place_id: str
    arrive: str
    minutes: int
    price_label: Optional[str] = None
    rating: Optional[float] = None
    maps_url: str = ""


class TripDay(BaseModel):
    day: int
    stops: list[TripStop]
    lunch: Optional[TripLunch] = None
    end_time: str


class TrafficWindow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    label: str
    from_: str = Field(alias="from")
    to: str
    level: Literal["heavy", "moderate", "light"]
    note: str = ""


class ModeOption(BaseModel):
    mode: TripMode
    total_minutes: Optional[int] = None
    total_km: Optional[float] = None
    note: str = ""


class TripCost(BaseModel):
    currency: str = "INR"
    travel: int
    food: int
    entry: Optional[int] = None
    total: int
    per_person: int
    assumptions: list[str] = Field(default_factory=list)
    is_estimate: bool = True


class TripPlan(BaseModel):
    version: int = 1
    plan_type: PlanType
    date: str
    start_time: str
    start_label: str = ""
    travelers: int
    objective: Objective
    days: list[TripDay]
    traffic_windows: list[TrafficWindow] = Field(default_factory=list)
    mode_options: list[ModeOption] = Field(default_factory=list)
    cost: TripCost
    tips: list[str] = Field(default_factory=list, max_length=4)
    warnings: list[str] = Field(default_factory=list, max_length=5)
    attribution: str = "Google Maps"


class TripPlanResponse(BaseModel):
    plans: list[TripPlan] = Field(default_factory=list)
    status: Literal["ok", "partial", "unsupported"] = "ok"
    warnings: list[str] = Field(default_factory=list)
