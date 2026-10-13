#!/usr/bin/env python3
"""Smoke-test a running (local or deployed) backend with real photos.

  python scripts/smoke_test.py https://your-api.onrender.com --origin https://your-app.vercel.app \
         --photo ../test_photos/IMG_4821.jpg --photo ../test_photos/IMG_4822.jpg --hint "Mumbai" --plan

Checks: health (and that it is NOT mock mode), CORS preflight for your frontend origin, optional photo
upload through /api/place-cards, optional /api/trip-plan from the confirmed places. Prints names, status and
confidence only (never coordinates) and exits non-zero if a check fails. Needs httpx (already in requirements).
"""
import argparse
import json
import re
import sys

import httpx

FAILS = []


def check(ok: bool, label: str, detail: str = ""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILS.append(label)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--origin", help="your frontend origin, e.g. https://your-app.vercel.app")
    ap.add_argument("--photo", action="append", default=[], help="photo path (repeat, max 10)")
    ap.add_argument("--hint", default=None)
    ap.add_argument("--plan", action="store_true", help="also build a trip plan from the places that resolved")
    ap.add_argument("--allow-mock", action="store_true", help="don't fail when the server is in mock mode")
    a = ap.parse_args()
    base = a.base_url.rstrip("/")
    c = httpx.Client(timeout=120)

    r = c.get(f"{base}/api/health")
    check(r.status_code == 200, "health reachable", str(r.status_code))
    h = r.json() if r.status_code == 200 else {}
    print("     ", h)
    check(a.allow_mock or h.get("mock_mode") is False, "live mode (MOCK_MODE=false)")
    check(base.startswith("https://") or "localhost" in base or "127.0.0.1" in base, "served over HTTPS")

    if a.origin:
        r = c.options(f"{base}/api/place-cards", headers={"Origin": a.origin, "Access-Control-Request-Method": "POST"})
        check(r.headers.get("access-control-allow-origin") == a.origin, "CORS allows your frontend origin",
              r.headers.get("access-control-allow-origin", "no header"))
        r = c.options(f"{base}/api/place-cards", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
        check(r.headers.get("access-control-allow-origin") in (None, ""), "CORS rejects other origins")

    cards = []
    if a.photo:
        files = [("images", (f"photo{i}.jpg", open(p, "rb"), "image/jpeg")) for i, p in enumerate(a.photo)]
        data = {"global_hint": a.hint} if a.hint else {}
        r = c.post(f"{base}/api/place-cards", files=files, data=data)
        check(r.status_code == 200, "place-cards upload", f"{r.status_code} {'' if r.status_code == 200 else r.text[:200]}")
        if r.status_code == 200:
            body = r.json()
            check(not re.search(r'"(lat|lng|latitude|longitude)"', json.dumps(body)), "response has no coordinates")
            for res in body["results"]:
                card = res.get("card") or {}
                print(f"      photos {res['photo_indexes']}: {res['status']:<14} {card.get('name', '-')}"
                      f"  [{card.get('confidence', '-')}/{card.get('source', '-')}]  candidates={len(res.get('candidates', []))}")
                if res["status"] == "ok" and card:
                    cards.append(card)

    if a.plan:
        ids = list({c_["place_id"] for c_ in cards})
        if len(ids) < 1:
            check(False, "trip plan", "no resolved places to plan with")
        else:
            r = c.post(f"{base}/api/trip-plan", json={"place_ids": ids, "start_time": "09:00", "travelers": 2})
            check(r.status_code == 200, "trip-plan", f"{r.status_code} {'' if r.status_code == 200 else r.text[:200]}")
            if r.status_code == 200:
                b = r.json()
                print(f"      status={b['status']} plans={[p['plan_type'] for p in b['plans']]}")
                check(not re.search(r'"(lat|lng|latitude|longitude)"', json.dumps(b)), "plan has no coordinates")
                for p in b["plans"]:
                    legs = [s["leg_from_previous"] for d in p["days"] for s in d["stops"] if s["leg_from_previous"]]
                    check(all(l["duration_in_traffic_min"] >= l["duration_min"] for l in legs), f"{p['plan_type']}: traffic time >= base time")

    print("\nALL CHECKS PASSED" if not FAILS else f"\n{len(FAILS)} CHECK(S) FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
