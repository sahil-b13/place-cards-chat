# PROJECT_PLAN.md — "Place Cards": Opt-in Photo-to-Place Info + Travel Plan in CometChat Chat

> Put this file in the repo root as `PROJECT_PLAN.md`. To build, the user says only:
> **"Start building Phase N from PROJECT_PLAN.md"** (and attaches this file + the repo zip + `PROGRESS.md` if Phase > 1).

---

## 0. INSTRUCTIONS FOR CLAUDE (READ FIRST)

1. **Build ONLY the phase the user names.** Do not start the next phase unless the user asks. Each phase is sized to finish in one session.
2. **Token discipline.** Read only Sections 0–6 plus the requested phase in Section 7 (also Section 5B for Phases 5–6). Do not re-read other phases. Create files directly with tools; do not paste whole files back into chat. Final chat message after a phase: max ~15 lines.
3. **Resume protocol.** If `PROGRESS.md` exists, read it first, inspect the repo tree, and continue from it. Trust the repo over memory. If the repo is missing for Phase 2+, ask the user to upload the zip (one question, then proceed).
4. **Ask nothing you can decide.** Defaults are given below. Ask at most ONE question, only if truly blocked (e.g. repo missing).
5. **Honesty about verification.** Your sandbox may not reach Google, CometChat, or the internet. Detect this. Label every check as `verified in mock mode`, `verified live`, or `NOT verified (user must run: <exact command>)`. Never claim live verification you did not do.
6. **Secrets.** Never ask the user to paste API keys in chat. Keys live in `.env` files (git-ignored). Provide `.env.example` only.
7. **End of every phase:** update `PROGRESS.md` (template in Section 6), then reply with: what was built, exact commands to run/verify, what the user must supply next, and the next phase name.
8. **Use the CometChat MCP** (`claude mcp add --transport http cometchat https://mcp.cometchat.com/mcp?ref=z2c`) when it is available, for current docs/bundles in Phases 2–4. If MCP is not available in this environment, use official CometChat docs knowledge, say so in PROGRESS.md, and flag version-sensitive code for the user to verify. Package versions and UI Kit APIs change: always check the installed version's docs before writing integration code.

---

## 1. PROJECT SUMMARY

A CometChat-powered chat app where a user can attach 1–10 photos and **optionally** toggle "Add place info". If toggled on, the system identifies the place in each photo, fetches key details, lets the sender confirm or correct them, then sends the photos plus a compact **place card** to the receiver. If not toggled, photos send normally and nothing else happens.

**Card contents (kept deliberately short, to avoid overwhelming the receiver):**
place name · category · 1–2 sentence summary · address · rating (+count) · price level · open-now/hours today · 2–3 short user reviews · up to 3 nearby restaurants (landmarks) · website link · "Open in Maps" link.
For restaurants: same card plus price level and website/menu link. A full menu is NOT promised; Places API does not reliably provide one.

**Travel plan (opt-in, second toggle):** from the confirmed places the sender can ask for a one-day tour guide: best stop order (least time or least distance), drive/transit/walk legs with traffic-aware timing, a timeline from the chosen start time (arrival/departure per stop), a lunch stop at a sensible time near the route, nearby restaurants, busy/heavy-traffic windows to avoid, travel-mode options, a cost estimate, and a "cheapest" vs "comfort" variant with per-person split. It is sent as ONE custom message `trip_plan` that the receiver sees as a stop-by-stop timeline. **All numbers come from APIs or editable assumptions computed in code; the AI only writes short tips from those numbers and never invents figures.** Costs are estimates and are labeled as such.

**Why it's interesting:** opt-in AI enrichment inside chat, honest confidence handling, sender-in-the-loop confirmation, privacy-safe (never leaks raw GPS of the sender).

**Challenge context:** CometChat "Zero to Chat" Build Challenge (#ZeroToChat). Valid entry = it runs, CometChat MCP visibly used, demo video < 90 seconds, repo link, quote-tweet of the challenge thread tagging @CometChat. The user has ~4 days. If the challenge no longer accepts entries, the project is still a standalone portfolio piece; skip the submission steps.

---

## 2. KEY DESIGN DECISIONS (already made, don't relitigate)

| Topic | Decision | Reason |
|---|---|---|
| Place data source | **Google Places API (New)**, never scraping | Scraping violates Google ToS and breaks constantly |
| Location detection | Fallback chain: EXIF GPS → vision model reads signage/landmarks → user hint/correction | No single method is reliable for generic photos |
| Reliability strategy | **Sender confirms/edits** detected place before sending | Turns an unreliable guess into a dependable feature |
| AI provider | **Switchable via `VISION_PROVIDER=gemini\|anthropic`**, default `gemini` (free tier available). Gemini model from `GEMINI_MODEL`; Anthropic model from `VISION_MODEL` (`claude-haiku-5-5` is the cheap option). Do NOT hardcode a Gemini model name from memory: check the current model list/docs at build time | Free to start; both return the same VisionResult JSON, so the rest of the app doesn't care. Gemini free-tier terms may allow input use for product improvement: warn user in README |
| Mock mode | Mock fixtures are chosen by an explicit `MOCK_SCENARIO` setting or request order, **never by image filename** | Filename-based mocks look like real detection and mislead |
| Routing | **Google Routes API** (`computeRoutes`, `computeRouteMatrix`) with traffic-aware timing | Real drive times/distances; no guessing |
| Trip ordering | Brute-force permutations for ≤ 8 stops; nearest-neighbour + 2-opt for 9–10 | Optimal for small N, simple and fast |
| Trip costs | Code-computed from distance × editable per-km rates + Places price levels + user-entered entry fees | No API gives cab fares or ticket prices; show as estimate with listed assumptions |
| Trip scope v1 | One city/region, one day (auto-split into days if timeline runs past ~20:00). Stops > ~100 km apart or in different cities → warning, no plan | Flights/trains are a different problem |
| CometChat AI credits | **Not used.** Do not depend on any CometChat AI/token allowance | Free allowance unverified; AI runs on our own backend |
| Message transport | Photos as normal CometChat media messages + ONE custom message `customType: "place_cards"` carrying all cards | Opt-in is naturally separate; normal photos stay untouched |
| Backend | Python 3.11+, FastAPI, httpx, pydantic, rapidfuzz, pytest | Fast to build; user's prior stack is Python |
| Frontend | React + Vite (JavaScript), CometChat React UI Kit + JS SDK | Matches CometChat bundles |
| Dev without internet | `MOCK_MODE=true` returns fixtures for vision + places | Lets every backend phase be verified anywhere |
| Fallback if custom bubble fights UI Kit | Render the cards as a formatted text message (`FALLBACK_TEXT_CARDS=true`) | A working simple card beats a broken fancy one |

---

## 3. REPO STRUCTURE (target)

```
place-cards-chat/
  PROJECT_PLAN.md
  PROGRESS.md
  README.md
  .gitignore                 (must include .env, node_modules, .venv, __pycache__)
  test_photos/               (user supplies; not committed if large)
  backend/
    requirements.txt
    .env.example
    app/
      main.py                (FastAPI app, CORS, routes)
      config.py              (env settings)
      schemas.py             (pydantic models = contracts in Section 4)
      services/
        exif.py              (server-side EXIF fallback via Pillow)
        vision.py            (Gemini or Anthropic vision -> VisionResult, via VISION_PROVIDER)
        places.py            (Google Places client + MockPlaces)
        resolver.py          (resolution logic, Section 5)
        card_builder.py      (PlaceDetails -> compact Card)
        cache.py             (in-memory TTL cache keyed by place_id)
        routes.py            (Google Routes API client + MockRoutes)   [Phase 5]
        planner.py           (ordering, timeline, lunch, traffic windows, modes)   [Phase 5]
        costing.py           (cost estimate from costs.json assumptions)   [Phase 5]
        tips.py              (short AI tips from computed plan JSON; template fallback)   [Phase 5]
    costs.json               (editable per-km rates, meal budgets, default visit minutes)
    fixtures/                (mock vision + places + routes JSON)
    scripts/
      live_check.py          (run one real photo through the live pipeline, print result)
    tests/
  frontend/
    package.json
    .env.example
    src/
      main.jsx, App.jsx
      cometchat/             (init, login, config)
      components/
        PlaceInfoToggle.jsx  (photo picker + opt-in flow modal)
        ReviewStep.jsx       (confirm/edit/skip each detected place)
        PlaceCardsBubble.jsx (receiver/sender card carousel)
        TripPlanOptions.jsx  (start time, start place, travelers, cheapest/comfort)   [Phase 6]
        TripPlanBubble.jsx   (timeline view for sender and receiver)   [Phase 6]
      lib/
        exif.js              (exifr wrapper)
        image.js             (resize to max 1024px, JPEG)
        api.js               (backend client)
```

---

## 4. DATA CONTRACTS (use exactly; keep stable across phases)

### 4.1 Card (the compact object sent inside the CometChat custom message)
```json
{
  "place_id": "string",
  "name": "string",
  "category": "restaurant | landmark | cafe | park | other",
  "is_restaurant": true,
  "summary": "max 200 chars",
  "address": "string",
  "area": "neighbourhood/city, string",
  "rating": 4.4,
  "rating_count": 1200,
  "price_level": 2,
  "price_label": "₹₹",
  "open_now": true,
  "hours_today": "string or null",
  "reviews": [ { "author": "string", "rating": 5, "text": "max 160 chars", "when": "string" } ],
  "nearby": [ { "name": "string", "rating": 4.2, "distance_m": 150 } ],
  "website": "url or null",
  "maps_url": "url",
  "photo_indexes": [0, 2],
  "confidence": "high | medium | low",
  "source": "exif | vision | user",
  "attribution": "Google Maps"
}
```
Limits: `reviews` ≤ 3, `nearby` ≤ 3. Never include the sender's raw GPS. Venue coordinates are NOT included in the card (use `maps_url`). Keep the serialized card < ~4 KB (verify CometChat metadata size limits in docs).

### 4.2 `POST /api/place-cards` (multipart/form-data)
- `images`: 1–10 files (client already resized to ≤1024px JPEG)
- `meta`: JSON string array, one per image: `[{"index":0,"lat":19.07,"lng":72.87,"hint":"Colaba, Mumbai"}]` (lat/lng/hint optional)
- `global_hint`: optional string (e.g. city) applied to all photos

Response:
```json
{
  "results": [
    {
      "photo_indexes": [0, 2],
      "status": "ok | low_confidence | not_found",
      "card": { ...Card or null },
      "candidates": [ { "place_id": "...", "name": "...", "address": "..." } ]
    }
  ]
}
```
Photos resolving to the same `place_id` are merged into one result (dedupe), with all `photo_indexes`.

### 4.3 `POST /api/place-cards/resolve` (JSON)
`{ "query": "Cafe Leopold", "lat": null, "lng": null, "hint": "Mumbai" }` or `{ "place_id": "..." }` → `{ "status", "card", "candidates" }`. Used when the sender corrects or picks a candidate. Card `source` becomes `"user"`.

### 4.4 `GET /api/health` → `{ "status": "ok", "mock_mode": true }`

### 4.5 Vision result (internal)
```json
{
  "identifiable": true,
  "place_name": "string or null",
  "place_type": "string or null",
  "area_guess": "string or null",
  "country_guess": "string or null",
  "confidence": "high | medium | low",
  "evidence": ["short strings: e.g. 'sign reads ...'"]
}
```
Vision prompt rules: only name a place if there is visible evidence (signage, famous landmark, distinctive architecture); never guess a business from ambiance; output strict JSON only; if unsure set `identifiable=false`.

### 4.6 CometChat custom message
`customType: "place_cards"`, `customData: { "cards": [Card, ...], "version": 1 }`. Sent once, after the photo media messages.

### 4.7 TripPlan (compact object sent inside the `trip_plan` custom message)
```json
{
  "version": 1,
  "plan_type": "cheapest | comfort",
  "date": "YYYY-MM-DD",
  "start_time": "08:00",
  "start_label": "Colaba, Mumbai (text typed by sender, never raw GPS)",
  "travelers": 2,
  "objective": "least_time | least_distance",
  "days": [
    {
      "day": 1,
      "stops": [
        {
          "order": 1,
          "place_id": "string",
          "name": "string",
          "category": "string",
          "arrive": "08:25",
          "depart": "09:25",
          "visit_minutes": 60,
          "photo_indexes": [0],
          "maps_url": "url",
          "leg_from_previous": {
            "mode": "DRIVE | TRANSIT | WALK | TWO_WHEELER",
            "distance_km": 6.2,
            "duration_min": 25,
            "duration_in_traffic_min": 32
          }
        }
      ],
      "lunch": {
        "after_stop_order": 2,
        "name": "string",
        "place_id": "string",
        "arrive": "13:00",
        "minutes": 60,
        "price_label": "₹₹",
        "rating": 4.3,
        "maps_url": "url"
      },
      "end_time": "18:40"
    }
  ],
  "traffic_windows": [
    { "label": "Evening rush", "from": "17:00", "to": "20:00", "level": "heavy | moderate | light", "note": "string" }
  ],
  "mode_options": [
    { "mode": "TRANSIT", "total_minutes": 190, "total_km": 31.4, "note": "string" }
  ],
  "cost": {
    "currency": "INR",
    "travel": 1200,
    "food": 800,
    "entry": null,
    "total": 2000,
    "per_person": 1000,
    "assumptions": ["Cab ₹X/km (editable)", "Entry fees not included unless entered"],
    "is_estimate": true
  },
  "tips": ["max 4 short strings"],
  "warnings": ["e.g. 'Stop 3 may be closed at arrival time'"],
  "attribution": "Google Maps"
}
```
Limits: ≤ 10 stops, `tips` ≤ 4, `warnings` ≤ 5. Never include sender GPS. Keep serialized size small (verify CometChat metadata limits in docs); if too large, drop `mode_options` first, then shorten notes.

### 4.8 `POST /api/trip-plan` (JSON)
```json
{
  "place_ids": ["...", "..."],
  "photo_indexes_by_place": { "place_id": [0, 2] },
  "start_time": "08:00",
  "date": "YYYY-MM-DD or null (default: next Saturday)",
  "start": { "text": "Colaba, Mumbai", "place_id": null },
  "return_to_start": false,
  "travelers": 2,
  "objective": "least_time | least_distance",
  "variants": ["cheapest", "comfort"],
  "entry_fees": { "place_id": 100 }
}
```
Response: `{ "plans": [TripPlan, ...], "status": "ok | partial | unsupported", "warnings": [] }`. `unsupported` when stops are in different cities or > ~100 km apart.

### 4.9 CometChat custom message (trip plan)
`customType: "trip_plan"`, `customData: { "plans": [TripPlan, ...], "version": 1 }`. Sent once, after the `place_cards` message (or alone if the sender skipped place info).

---

## 5. RESOLUTION LOGIC (implement in `resolver.py`)

Per photo, in order:
1. **EXIF GPS present** (from client `lat/lng` or server Pillow fallback): Places Nearby Search (radius ~75 m, ranked by distance). Run vision in parallel. If vision names a place, pick the nearby candidate with best fuzzy name match (rapidfuzz ratio ≥ 70) → `ok`, source `exif`, confidence high. If vision gives no name: take the nearest named POI only if exactly one candidate is within ~30 m → `medium`; otherwise `low_confidence` with up to 5 candidates for the sender to choose.
2. **No GPS, vision names a place** (confidence high/medium): Text Search `"<place_name> <area_guess or hint>"`, biased by `hint` if given. Accept only if top result fuzzy-matches the vision name (≥ 70) → `ok`/`medium`. Else `low_confidence` with candidates.
3. **Neither:** `not_found`, UI asks the sender to type a place name or skip the photo.
4. **Privacy guardrail:** if a GPS point has no public POI/landmark nearby (likely a home or private location), return `not_found` rather than a street address. Never output the sender's coordinates.
5. **Landmarks:** if `category` is landmark/park/attraction (not restaurant), fetch up to 3 nearby restaurants (rating-ranked, within ~500 m) for `nearby`. For restaurants, skip `nearby`.
6. **Batching:** process photos concurrently (asyncio, semaphore of 4). Dedupe by `place_id` after resolution. Cache place details by `place_id` (TTL 24 h) to save API cost.
7. **Google Places (New) usage:** `POST places.googleapis.com/v1/places:searchText`, `:searchNearby`, and `GET /v1/places/{id}`; auth via `X-Goog-Api-Key`; always send a tight `X-Goog-FieldMask` (displayName, formattedAddress, location, rating, userRatingCount, priceLevel, reviews, regularOpeningHours, currentOpeningHours, websiteUri, googleMapsUri, editorialSummary, types, primaryType). Reviews/rating/hours are higher-cost fields: cache, and fetch details only for the final chosen place, not every candidate. Check current pricing/free allowance at build time. Show "Google Maps" attribution on cards.
8. **Summary text:** use `editorialSummary` if present; else generate a 1-sentence summary from vision/place types (no hallucinated facts: only use data present).

---

## 5B. TRIP PLANNER LOGIC (implement in `planner.py`, `routes.py`, `costing.py`, `tips.py`)

**Principle:** code and APIs produce every number; the AI only phrases tips from the finished JSON and must not add facts or figures. If the AI call fails, use template tips.

1. **Inputs:** confirmed `place_ids` (fetch coordinates from cached place details, server-side only), start time/date, optional start point (typed text or place, geocoded via Places text search; never raw GPS), travelers, objective, variants.
2. **Scope check:** if stops span different cities or max pairwise distance > ~100 km → `unsupported` with a clear message.
3. **Distance matrix:** one `computeRouteMatrix` call (DRIVE, traffic-aware, departure at the planned start time on the plan date; use a future date because traffic-aware needs future departure). Cache by (origin, destination, hour bucket).
4. **Ordering:** `least_time` uses matrix durations, `least_distance` uses matrix distances. ≤ 8 stops: evaluate all permutations (start fixed if given). 9–10 stops: nearest-neighbour then 2-opt. If `return_to_start`, include the return leg.
5. **Timeline:** per stop, `arrive = previous depart + leg duration_in_traffic`; `depart = arrive + visit_minutes`. Default `visit_minutes` by category from `costs.json` (e.g. landmark 45, park 60, restaurant 60, other 45), editable. Check each stop's `regularOpeningHours` against arrival; add a `warnings` entry if likely closed (do not silently reorder).
6. **Lunch:** target window 12:30–14:00. Find the stop boundary whose clock time falls closest to 13:00; search restaurants near that stop (`searchNearby`, ~500 m, rating-ranked, must be open at that time, price level fits the variant). Insert a 60-minute lunch and shift later stops. If the day starts after 12:00 or ends before 12:30, skip lunch.
7. **Day split:** if the timeline passes ~20:00, move remaining stops to Day 2 starting at the same start time.
8. **Traffic windows:** for the chosen order, call `computeRoutes` for each leg (or the whole route) at several departure slots (e.g. 08, 10, 12, 14, 16, 18, 20). Compute ratio = duration_in_traffic / static duration. Label `heavy` ≥ 1.5, `moderate` 1.2–1.5, else `light` (thresholds in `costs.json`). Output merged windows plus a "best departure time" tip. This is a modelled estimate, not an official Google "busy hours" feed; say so in README.
9. **Mode options:** compare DRIVE, TRANSIT, WALK, and TWO_WHEELER where Routes API supports it in the region (check docs). Report total minutes and km per mode where available. Transit coverage may be partial: say "not available" rather than guessing.
10. **Variants:**
   - `cheapest`: prefer TRANSIT/WALK for legs where total time is within a configurable factor (default 1.8×) of driving, otherwise shared/budget cab or auto rates; lunch place price level ≤ 2.
   - `comfort`: DRIVE (cab/car) for all legs; lunch price level ≥ 2 if available, best rating.
11. **Cost:** `costing.py` reads `costs.json` assumptions (cab per km, auto per km, transit estimate per leg, fuel per km, meal budget by price level, all clearly labeled placeholders for the user's city). `travel` = Σ leg cost by mode; `food` = lunch (and optional snack) by price level × travelers; `entry` = sum of user-entered fees, else `null` ("not included"). `per_person = total / travelers`. Always set `is_estimate: true` and list `assumptions`.
12. **Mock mode:** `MockRoutes` returns deterministic fixtures (no real traffic) so planner logic is fully testable offline. Label outputs `verified in mock mode`.

---

## 6. HANDOFF PROTOCOL — `PROGRESS.md` TEMPLATE

At the end of every phase, create/update `PROGRESS.md` in the repo root:

```
# PROGRESS
## Completed phases
- Phase N: <one line> — date — verification status (mock / live / not verified)
## Current state
- How to run backend: <exact commands>
- How to run frontend: <exact commands>
- Env vars needed (names only): ...
## File map (key files only, one line each)
## Decisions / deviations from PROJECT_PLAN.md
## Known issues / TODO
## User must supply before next phase
## NEXT: Phase N+1 — <name>
```
Account-switch procedure for the user: zip the repo **excluding** `node_modules`, `.venv`, `.env`; upload `PROJECT_PLAN.md` + zip in the new chat; say "Start building Phase N+1 from PROJECT_PLAN.md".

---

## 7. PHASES

### PHASE 1 — Backend: place-intelligence service (mock-first)
**Needs from user:** nothing (runs in mock mode). For live verification later: `ANTHROPIC_API_KEY`, `GOOGLE_PLACES_API_KEY` in `backend/.env`.

**Build:**
1. Repo skeleton (Section 3), `.gitignore`, `README.md` stub, `PROGRESS.md`.
2. `config.py` (env: `MOCK_MODE`, `MOCK_SCENARIO`, `VISION_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `ANTHROPIC_API_KEY`, `VISION_MODEL`, `GOOGLE_PLACES_API_KEY`, `ALLOWED_ORIGINS`, `CACHE_TTL_SECONDS`), `schemas.py` per Section 4.
3. `vision.py`: provider switch (`VISION_PROVIDER`). Real Gemini call and real Anthropic call (image as base64, same strict-JSON prompt per 4.5, tolerant JSON parsing, timeout, one retry) + mock path reading `fixtures/vision_*.json`. **Mock fixtures are selected by `MOCK_SCENARIO` or request order, NEVER by image filename.**
4. `places.py`: `PlacesClient` (searchText, searchNearby, getDetails with field masks) + `MockPlaces` using `fixtures/places_*.json`. Include at least 4 fixtures: a restaurant with signage (e.g. Cafe Leopold, Colaba), a landmark (e.g. Gateway of India) with nearby restaurants, an ambiguous result (multiple candidates), and a not-found case.
5. `exif.py` (Pillow GPS extraction), `cache.py`, `card_builder.py` (truncation, price label mapping: 0 free, 1 `₹`, 2 `₹₹`, 3 `₹₹₹`, 4 `₹₹₹₹`), `resolver.py` per Section 5.
6. `main.py`: routes 4.2, 4.3, 4.4; CORS from `ALLOWED_ORIGINS`; file-size and count limits (≤10 images, ≤2 MB each); clear error JSON.
7. Tests (pytest + TestClient, mock mode): resolver branches (exif+vision match, vision-only, ambiguous, not_found, privacy guardrail), dedupe merge, truncation limits, price label, endpoint happy path and validation errors.

**Done when:** `pytest` passes; `uvicorn app.main:app --reload` starts; a curl example for `/api/place-cards` (document it in README) returns a valid mock response; `PROGRESS.md` updated with exact live-verification steps (set keys, `MOCK_MODE=false`, run a sample photo).
**Stop** after this. Do not start the frontend.

---

### PHASE 1B — Go live: real photo detection (do this as soon as a backend exists)
**Why:** if results only depend on the photo's filename, the backend is running mock fixtures (or the code reads the filename). This phase makes detection read the actual image.
**Needs from user:** in `backend/.env`: `GEMINI_API_KEY` (free, from Google AI Studio) or `ANTHROPIC_API_KEY`; `GOOGLE_PLACES_API_KEY` (Places API (New) enabled, billing account attached, budget alert set); 8–10 test photos in `test_photos/` with generic names like `IMG_4821.jpg`.

**Build:**
1. **Audit:** search the whole backend and frontend for any use of the uploaded filename (`filename`, `.name`, `os.path.basename`, string matching against fixture names). Remove every such dependency from detection logic. Report what was found in PROGRESS.md.
2. Make mock fixture selection use `MOCK_SCENARIO` / request order only.
3. Implement/confirm the `VISION_PROVIDER` switch and `GEMINI_MODEL` handling (check current Gemini docs for SDK/REST usage and current model names; do not rely on memory).
4. `/api/health` returns `{ "status": "ok", "mock_mode": false, "vision_provider": "gemini" }`.
5. `scripts/live_check.py <image_path> [--hint "city"]`: runs the real pipeline on one photo and prints vision result, chosen place, status, confidence, and source. Add a `--compare` flag that runs both providers on the same photo for side-by-side comparison.
6. Honest-failure behaviour: if a key is missing while `MOCK_MODE=false`, return a clear error naming the missing variable; never silently fall back to mock.

**Done when (label each `verified live` or `NOT verified (user must run: ...)`):** the same photo renamed to two different filenames returns the same place; a photo of a famous landmark and a photo with a readable shop sign both resolve; a generic photo returns `low_confidence`/`not_found` rather than a confident wrong place; `--compare` output recorded in PROGRESS.md so the user can choose a provider.

---

### PHASE 2 — Frontend scaffold + working CometChat chat
**Needs from user:** CometChat **App ID, Auth Key, Region** in `frontend/.env` (names: `VITE_COMETCHAT_APP_ID`, `VITE_COMETCHAT_AUTH_KEY`, `VITE_COMETCHAT_REGION`), and two test users (e.g. `user1`, `user2`; Claude provides a script/instructions to create them, or the user creates them in the CometChat dashboard).

**Build:**
1. Use the CometChat MCP/docs to confirm current package names and init pattern for the React UI Kit + JS SDK; install them with Vite React. Record exact versions in PROGRESS.md.
2. `cometchat/` init and login. A simple login screen: choose `user1` or `user2` (dev-only; note that Auth Key in the client is for demos only).
3. Conversations list + message view (UI Kit components) so two browser windows can chat, including sending normal photos.
4. `.env.example`, README run steps, a backend `VITE_API_BASE_URL` placeholder (not used yet).

**Done when:** two browser windows logged in as different users exchange text and a normal photo in real time (user verifies; mark `NOT verified` if the sandbox can't reach CometChat). No place-card features yet.
**Challenge validity note:** record in PROGRESS.md which MCP tools/docs were used (the user will screen-record the MCP in action for the demo).

---

### PHASE 3 — Opt-in flow: photos → backend → confirm → send
**Needs from user:** Phase 1 backend runnable (mock or live) and Phase 2 chat working. For real results: `backend/.env` keys and 6–10 test photos in `test_photos/`.

**Build:**
1. In the message composer area add a **"📍 Place info" button** (use the UI Kit's attachment/auxiliary options hook; confirm the current API in docs). The existing normal attachment path stays unchanged and sends photos as usual.
2. `PlaceInfoToggle.jsx` flow modal: pick 1–10 photos → client `image.js` resizes (max 1024px JPEG) → `exif.js` (exifr) reads GPS per photo → optional "city/area hint" input → call `POST /api/place-cards` with a loading state.
3. `ReviewStep.jsx`: show each result group with its photo thumbnails and card preview. Per group: **Confirm**, **Change** (search box → `/api/place-cards/resolve`, or pick from `candidates`), **Skip place info for these photos**. `low_confidence`/`not_found` groups are highlighted and require a decision.
4. On **Send**: send each photo with `sendMediaMessage`, then ONE custom message `place_cards` (4.6) with only confirmed cards. If all cards are skipped, send photos normally with no custom message.
5. Basic error handling: backend down, timeout, zero results (offer "send photos without place info").

**Done when:** from the UI, selecting photos with the opt-in sends the photos plus a `place_cards` custom message; skipping sends only photos. The receiver may still see raw/unknown custom message (rendering is Phase 4). Verify by inspecting the received message object in the console or CometChat dashboard.

---

### PHASE 4 — Receiver-side card rendering
**Needs from user:** Phases 1–3 working.

**Build:**
1. `PlaceCardsBubble.jsx`: horizontally scrollable cards. Each card: name + category chip, rating stars + count, price label, open-now badge + today's hours, 1–2 line summary, address, **Reviews** (collapsed; shows 2–3 short snippets on expand), **Nearby restaurants** (collapsed, landmarks only), website link, **"Open in Maps"** button, small "Google Maps" attribution. A small label "Photo 1, 3" showing which photos the card refers to.
2. Register as a custom message template for `customType: "place_cards"` via the UI Kit's message-template mechanism (confirm API in docs). Same bubble for sender and receiver.
3. **Fallback:** if the template integration cannot be made to work after one honest attempt, implement `FALLBACK_TEXT_CARDS`: the sender client sends the cards as one formatted text message instead, and document it in PROGRESS.md.
4. Mobile-responsive layout, loading/empty states, text truncation. Information stays compact; no wall of text.

**Done when:** sending photos with place info from `user1` shows readable cards to `user2` in real time; expanding reviews/nearby works; "Open in Maps" opens the right place; normal photos without the toggle show no cards.

---

### PHASE 5 — Trip planner backend (mock-first)
**Needs from user:** nothing for mock mode. For live verification: Routes API enabled on the same Google Cloud project/key, and 4–6 confirmed places in one city.

**Build (follow Section 5B exactly):**
1. `routes.py`: `RoutesClient` (`computeRouteMatrix`, `computeRoutes`, tight field masks, traffic-aware, timeouts, one retry) + `MockRoutes` with fixtures (≥ 5 stops, including one case with a stop likely closed at arrival and one cross-city `unsupported` case).
2. `planner.py`: scope check, ordering (permutations ≤ 8, NN + 2-opt for 9–10), timeline, opening-hours warnings, lunch insertion, day split, traffic windows, mode options, `cheapest`/`comfort` variants.
3. `costing.py` + `costs.json`: editable assumptions, entry-fee input, `per_person`.
4. `tips.py`: ≤ 4 short tips from the computed plan JSON via the configured provider; strict instruction to use only numbers present in the JSON; template fallback if the call fails or output mentions a number not in the plan.
5. `POST /api/trip-plan` per 4.8; schemas for 4.7; validation (1–10 `place_ids`, valid time format, travelers 1–20).
6. Tests (pytest, mock mode): permutation ordering picks the shortest by time and by distance, timeline arithmetic from 08:00, lunch lands in the 12:30–14:00 window, day split, closed-at-arrival warning, `unsupported` for cross-city, cost totals and `per_person`, cheapest < comfort cost in the fixture case, tips never introduce unlisted numbers, payload size under the limit.

**Done when:** `pytest` passes; a documented curl for `/api/trip-plan` returns a valid mock plan; PROGRESS.md lists exact live-verification steps (real keys, `MOCK_MODE=false`, one real route). **Stop.** Do not start the frontend.

---

### PHASE 6 — Trip planner UI + receiver timeline
**Needs from user:** Phases 3–5 working.

**Build:**
1. In the "📍 Place info" modal, add a second toggle **"Make a travel plan"** (only enabled after at least one place is confirmed). `TripPlanOptions.jsx`: start time, start place (typed text only), travelers, objective (least time / least distance), plan type (cheapest / comfort / both), optional entry fee per stop, optional date.
2. Call `POST /api/trip-plan` with confirmed `place_ids` and show a preview (loading, errors, `unsupported` message, warnings) before sending.
3. On **Send**: photos, then `place_cards` (if any), then ONE custom message `trip_plan` (4.9).
4. `TripPlanBubble.jsx` (same for sender and receiver; register via UI Kit message-template as in Phase 4): vertical timeline Stop 1 → leg (mode, km, minutes with traffic) → Stop 2 → lunch → … → end time; tabs for Cheapest/Comfort; cost summary with per-person and the assumptions list; traffic-window chips ("avoid 17:00–20:00"); mode options (collapsed); warnings; "Open in Maps" per stop; "Google Maps" attribution; clear "Estimates" label.
5. **Fallback:** if the template integration fails after one honest attempt, send the plan as one formatted text message (`FALLBACK_TEXT_CARDS`) and document it.
6. Mobile-responsive, compact, no wall of text.

**Done when:** from the UI, user1 selects photos, confirms places, enables the travel plan, sends; user2 sees the timeline in real time; skipping the travel plan sends nothing extra.

---

### PHASE 7 — Hardening, privacy, deploy, demo, submission
**Needs from user:** hosting accounts (e.g. Vercel for frontend, Render/Railway/Fly for backend), real API keys set in host environment variables.

**Build:**
1. **Privacy & safety:** confirm the sender's raw GPS is never sent in messages (including `trip_plan`: start point is typed text only; warn in README about free-tier AI terms); confirm the residential/no-POI guardrail; strip EXIF from images before upload to the backend if not needed; do not store uploaded images (process in memory); document this in README.
2. **Reliability:** request timeouts, retries on transient Google/Anthropic errors, per-IP rate limit, request-size limits, cache hit logging, graceful partial results (some photos fail, others succeed).
3. **Cost control:** tight field masks, cache by `place_id` and by route (origin, destination, hour bucket), cap photos per request and stops per plan, free-tier Gemini and cheaper Anthropic option documented, Routes API call count per plan logged.
4. **Deploy:** backend with public HTTPS URL and CORS set to the frontend origin; frontend env pointing to it; smoke-test with real photos. Document deploy steps.
5. **README:** problem, demo GIF/video link, architecture diagram (mermaid), setup, env vars, how the resolution chain works, known limitations (generic photos, no full menus, Places API cost), CometChat features/MCP tools used.
6. **Demo script** (< 90 s, see Section 8) and a pre-recording checklist: run every demo photo through the real pipeline first and note the actual output; use only photos that resolve well, plus ONE deliberately ambiguous photo to show the confirm/change step.
7. **Submission (only if the challenge still accepts entries):** public repo, quote-tweet the challenge thread (https://x.com/CometChat/status/2103065271233888471) with the video + repo link, tag @CometChat, `#ZeroToChat`. Leave buffer before any deadline.

**Done when:** deployed app works with real photos end to end, README complete, demo script finalized.

---

## 8. DEMO SCRIPT (< 90 seconds)

| Time | Action | Shows |
|---|---|---|
| 0–8 s | Title + one-line pitch; briefly show the CometChat MCP being used in the editor/agent | Validity: MCP visible |
| 8–16 s | user1 sends 2 normal photos (toggle off) | Opt-in: normal photos unchanged |
| 16–30 s | user1 picks 4 photos (restaurant with signage, a landmark, a GPS-tagged photo, one ambiguous), toggles "📍 Place info" | Real detection (photos have generic filenames) |
| 30–42 s | Confirm step: confirm two, fix the ambiguous one by picking a candidate | Honest confidence, human in the loop |
| 42–55 s | user2's screen: compact cards appear; expand reviews, tap "Open in Maps" | Place cards payoff |
| 55–80 s | user1 toggles "Make a travel plan" (start 8:00, 2 travelers); user2 sees the timeline: stops, drive times, lunch, traffic window to avoid, cheapest vs comfort cost | Tour-guide payoff |
| 80–90 s | Wrap: opt-in, privacy-safe (no raw GPS), Google Maps data, built with CometChat | Close |

Pre-record: run every demo photo and the plan through the real pipeline first; use only photos/plans that resolve well plus ONE deliberately ambiguous photo.

---

## 9. GUARDRAILS

- Never scrape Google Maps. Never expose API keys in the frontend: Google and Anthropic keys exist only in the backend.
- Do not invent facts on cards; only use fields returned by the data source.
- Do not promise full menus; show price level + website/menu link.
- Do not depend on any CometChat AI credit/token allowance.
- Do not leak the sender's raw coordinates or a private address.
- Do not add features beyond the phase being built (no accounts system, database, payments, push notifications).
- CometChat Auth Key in the client is dev/demo only; state that in README.
- Travel plans: never let the AI generate distances, times, prices or opening hours; they come from APIs or labeled assumptions. Costs always carry `is_estimate: true` and an assumptions list. Never claim "official" busy hours; traffic windows are modelled estimates.
- Detection must never depend on the uploaded filename. Never silently fall back to mock when `MOCK_MODE=false`.
- Never expose `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, or Google keys in the frontend.

---

## 10. USER PREP CHECKLIST

| Item | Needed from | Notes |
|---|---|---|
| Gemini API key (free tier, Google AI Studio) | Phase 1B | Default vision provider; put in `backend/.env`, never in chat; read the free-tier data terms |
| Anthropic API key (optional) | Phase 1B if you pick `VISION_PROVIDER=anthropic` | Pay-per-use, separate from a Claude.ai subscription; `claude-haiku-5-5` is cheapest |
| Google Cloud project + **Places API (New)** enabled + API key | Phase 1B / Phase 7 | Billing account is usually required; restrict the key; set a budget alert; check current free allowance |
| **Routes API** enabled on the same project | Phase 5 (live check) | Needed for traffic-aware travel plans; same billing account |
| CometChat account: App ID, Auth Key, Region | Phase 2 | Free at app.cometchat.com; run MCP add command |
| Two CometChat test users (`user1`, `user2`) | Phase 2 | Dashboard or script |
| 8–10 test photos in `test_photos/` (generic filenames, same city for trip plans) | Phase 1B+ | 2 original phone photos with GPS (not screenshots), 2 famous landmarks, 2 restaurants with visible signage, 2 generic/ambiguous |
| Node 18+ and Python 3.11+ on your machine | Phase 1+ | To run and verify live |
| Hosting accounts | Phase 7 | Vercel + Render/Railway/Fly |
