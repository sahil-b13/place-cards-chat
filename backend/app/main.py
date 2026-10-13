import io
import json
import logging
import os
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import hardening
from .config import Settings, load_settings
from .schemas import (PhotoMeta, PlaceCardsResponse, ResolveRequest, ResolveResponse, TripPlanRequest,
                      TripPlanResponse)
from .services.cache import TTLCache
from .services.places import MockPlaces, PlacesClient
from .services.resolver import PhotoInput, Resolver
from .services import costing
from .services.planner import PlanInputError, TripPlanner
from .services.routes import MockRoutes, RoutesClient
from .services.tips import build_text_llm
from .services.vision import MockVision, build_vision

log = logging.getLogger("placecards")

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code, self.code, self.message = status_code, code, message


def _err(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, **extra}})


def build_resolver(settings: Settings) -> Resolver:
    cache = TTLCache(settings.cache_ttl_seconds)
    if settings.mock_mode:
        return Resolver(MockPlaces(FIXTURES_DIR), MockVision(FIXTURES_DIR, settings.mock_scenario), cache)
    # Live mode never falls back to mock: a missing key is a startup error naming the variable.
    if not settings.google_places_api_key:
        raise RuntimeError("MOCK_MODE=false but GOOGLE_PLACES_API_KEY is missing (set it in backend/.env)")
    vision = build_vision(settings.vision_provider, gemini_api_key=settings.gemini_api_key,
                          gemini_model=settings.gemini_model, anthropic_api_key=settings.anthropic_api_key,
                          vision_model=settings.vision_model)
    return Resolver(PlacesClient(settings.google_places_api_key), vision, cache)


def build_planner(settings: Settings, resolver: Resolver) -> TripPlanner:
    costs = costing.load_costs()
    if settings.mock_mode:
        return TripPlanner(resolver.places, MockRoutes(FIXTURES_DIR), resolver.cache, costs, llm=None)
    # Routes API uses the same Google key (Routes API must be enabled on the project).
    llm = build_text_llm(settings.vision_provider, settings.gemini_api_key, settings.gemini_model,
                         settings.anthropic_api_key, settings.vision_model)
    return TripPlanner(resolver.places, RoutesClient(settings.google_places_api_key, cache=resolver.cache),
                       resolver.cache, costs, llm=llm)


def _parse_meta(raw: Optional[str], n_images: int) -> dict[int, PhotoMeta]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ApiError(400, "invalid_meta", "meta must be a JSON array string")
    if not isinstance(data, list):
        raise ApiError(400, "invalid_meta", "meta must be a JSON array")
    out: dict[int, PhotoMeta] = {}
    for item in data:
        try:
            m = PhotoMeta(**item) if isinstance(item, dict) else None
        except ValidationError:
            m = None
        if m is None:
            raise ApiError(400, "invalid_meta", "each meta entry needs an integer index; lat/lng/hint must be valid")
        if m.index >= n_images or m.index in out:
            raise ApiError(400, "invalid_meta", f"meta index {m.index} is out of range or duplicated")
        out[m.index] = m
    return out


def create_app(settings: Optional[Settings] = None, resolver: Optional[Resolver] = None,
               planner: Optional[TripPlanner] = None) -> FastAPI:
    settings = settings or load_settings()
    resolver = resolver or build_resolver(settings)
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = FastAPI(title="Place Cards API", version="1.0.0")
    app.state.settings = settings
    app.state.resolver = resolver
    planner = planner or build_planner(settings, resolver)
    app.state.planner = planner

    hardening.install(app, settings)  # size limits + per-IP rate limit (added first, so CORS wraps it)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return _err(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"loc": [str(x) for x in e.get("loc", [])], "msg": e.get("msg", "")} for e in exc.errors()]
        return _err(422, "validation_error", "Request validation failed", details=details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return _err(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")  # no coordinates are logged anywhere
        return _err(500, "internal_error", "Something went wrong")

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "mock_mode": settings.mock_mode,
                "vision_provider": "mock" if settings.mock_mode else settings.vision_provider}

    @app.post("/api/place-cards", response_model=PlaceCardsResponse)
    async def place_cards(
        images: list[UploadFile] = File(default=[]),
        meta: Optional[str] = Form(default=None),
        global_hint: Optional[str] = Form(default=None),
    ):
        if not images:
            raise ApiError(400, "no_images", "Attach between 1 and %d images" % settings.max_images)
        if len(images) > settings.max_images:
            raise ApiError(400, "too_many_images", f"At most {settings.max_images} images per request")
        metas = _parse_meta(meta, len(images))
        hint = (global_hint or "").strip()[:120] or None

        photos: list[PhotoInput] = []
        for i, f in enumerate(images):
            data = await f.read(settings.max_image_bytes + 1)
            if len(data) > settings.max_image_bytes:
                raise ApiError(413, "image_too_large",
                               f"Image {i} exceeds {settings.max_image_bytes // (1024 * 1024)} MB")
            try:
                with Image.open(io.BytesIO(data)) as im:
                    im.verify()
            except Exception:
                raise ApiError(400, "invalid_image", f"Image {i} is not a valid image file")
            m = metas.get(i)
            photos.append(PhotoInput(index=i, data=data,
                                     lat=m.lat if m else None, lng=m.lng if m else None,
                                     hint=(m.hint or None) if m else None))
        h0, m0 = resolver.cache.hits, resolver.cache.misses
        results = await resolver.resolve_photos(photos, hint)
        # counts only: no coordinates, hints, names or image data are logged
        ok = sum(1 for r in results if r.status == "ok")
        log.info("place-cards: photos=%d groups=%d ok=%d cache hits=%d misses=%d", len(photos), len(results), ok,
                 resolver.cache.hits - h0, resolver.cache.misses - m0)
        return PlaceCardsResponse(results=results)

    @app.post("/api/place-cards/resolve", response_model=ResolveResponse)
    async def resolve(req: ResolveRequest):
        if not (req.place_id or (req.query and req.query.strip())):
            raise ApiError(400, "missing_query", "Provide either 'query' or 'place_id'")
        return await resolver.resolve_query(req)

    @app.post("/api/trip-plan", response_model=TripPlanResponse, response_model_by_alias=True)
    async def trip_plan(req: TripPlanRequest):
        h0, m0 = resolver.cache.hits, resolver.cache.misses
        try:
            result = await planner.plan(req)
            log.info("trip-plan: places=%d status=%s plans=%d cache hits=%d misses=%d", len(req.place_ids),
                     result.status, len(result.plans), resolver.cache.hits - h0, resolver.cache.misses - m0)
            return result
        except PlanInputError as e:
            status = 404 if e.code == "places_not_found" else 400
            raise ApiError(status, e.code, e.message)

    return app


app = create_app()
