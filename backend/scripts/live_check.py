#!/usr/bin/env python3
"""Run ONE real photo through the live pipeline and print what happened.

  cd backend
  python scripts/live_check.py ../test_photos/IMG_4821.jpg --hint "Mumbai"
  python scripts/live_check.py ../test_photos/IMG_4821.jpg --compare   # gemini vs anthropic

Reads keys from backend/.env (same as the server). Never uses mock data and never reads the
filename for detection. Coordinates are not printed.
"""
import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import load_settings  # noqa: E402
from app.services.cache import TTLCache  # noqa: E402
from app.services.places import PlacesClient  # noqa: E402
from app.services.resolver import PhotoInput, Resolver  # noqa: E402
from app.services.vision import build_vision  # noqa: E402


def make_vision(settings, provider):
    return build_vision(provider, gemini_api_key=settings.gemini_api_key, gemini_model=settings.gemini_model,
                        anthropic_api_key=settings.anthropic_api_key, vision_model=settings.vision_model)


async def run_one(settings, provider, data, hint):
    """Returns (vision_result_or_error, place_result, seconds)."""
    vision = make_vision(settings, provider)
    t0 = time.time()
    try:
        v = await vision.analyze(data, hint, 0)
    except Exception as e:  # report, don't hide
        v = f"VISION ERROR: {type(e).__name__}: {e}"
    resolver = Resolver(PlacesClient(settings.google_places_api_key), vision, TTLCache(60))
    res = (await resolver.resolve_photos([PhotoInput(index=0, data=data, hint=None)], hint))[0]
    return v, res, time.time() - t0


def show(provider, model, v, res, secs):
    print(f"\n=== provider: {provider} ({model}) — {secs:.1f}s ===")
    if isinstance(v, str):
        print(v)
    else:
        print(f"vision: identifiable={v.identifiable} name={v.place_name!r} type={v.place_type!r} "
              f"area={v.area_guess!r} confidence={v.confidence}")
        for e in v.evidence:
            print(f"  evidence: {e}")
    print(f"status: {res.status}")
    if res.card:
        c = res.card
        print(f"chosen place: {c.name} — {c.address}")
        print(f"confidence: {c.confidence}   source: {c.source}   category: {c.category}   "
              f"rating: {c.rating} ({c.rating_count})")
    for cand in res.candidates:
        print(f"  candidate: {cand.name} — {cand.address}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--hint", default=None, help='city/area hint, e.g. "Mumbai"')
    ap.add_argument("--compare", action="store_true", help="run both providers on the same photo")
    ap.add_argument("--provider", choices=["gemini", "anthropic"], help="override VISION_PROVIDER")
    a = ap.parse_args()

    s = load_settings()
    if not s.google_places_api_key:
        sys.exit("GOOGLE_PLACES_API_KEY is missing (set it in backend/.env)")
    with open(a.image, "rb") as f:
        data = f.read()
    providers = ["gemini", "anthropic"] if a.compare else [a.provider or s.vision_provider]
    for p in providers:
        model = s.gemini_model if p == "gemini" else s.vision_model
        try:
            v, res, secs = asyncio.run(run_one(s, p, data, a.hint))
        except RuntimeError as e:  # missing key etc.
            print(f"\n=== provider: {p} — skipped: {e} ===")
            continue
        show(p, model, v, res, secs)


if __name__ == "__main__":
    main()
