import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  readPlans, normalizePlan, formatMinutes, formatKm, formatMoney, legText, trafficChipText, lunchAfter,
  modeOptionText, previewText, formatTextPlan, stopCount,
} from "./tripView.js";
import {
  DEFAULT_TRIP_OPTIONS, validateTripOptions, buildTripRequest, sanitizePlan, preparePlansForSend, byteLength,
  messagePayload, MAX_PLAN_BYTES,
} from "./trip.js";

// Real mock-mode response captured from POST /api/trip-plan (backend Phase 5)
const real = JSON.parse(readFileSync(new URL("./fixtures/trip_response.json", import.meta.url), "utf8"));

test("real backend response normalises: both plans, stops, lunch, cost, windows", () => {
  const plans = readPlans({ plans: real.plans });
  assert.deepEqual(plans.map((p) => p.plan_type), ["cheapest", "comfort"]);
  const p = plans[1];
  assert.equal(stopCount(p), 5);
  assert.equal(p.days[0].stops[0].leg?.mode, "DRIVE");
  assert.ok(p.days[0].lunch && lunchAfter(p.days[0], p.days[0].stops.find((s) => s.order === p.days[0].lunch.after_stop_order)));
  assert.equal(p.cost.entry, 200); // 100 pp x 2 travelers
  assert.ok(p.traffic_windows.length > 0);
  assert.equal(p.attribution, "Google Maps");
  assert.ok(p.days[0].stops.find((s) => s.place_id === "mock_csmt").photo_indexes.join() === "0,2");
});

test("untrusted payloads are validated and clamped", () => {
  assert.deepEqual(readPlans(null), []);
  assert.deepEqual(readPlans({ plans: "x" }), []);
  assert.equal(normalizePlan({ plan_type: "premium", days: [] }), null); // unknown plan type
  assert.equal(normalizePlan({ plan_type: "comfort", days: [] }), null); // no stops
  const evil = JSON.parse(JSON.stringify(real.plans[0]));
  evil.days[0].stops[0].maps_url = "javascript:alert(1)";
  evil.days[0].stops[0].name = "x".repeat(500);
  evil.days[0].stops[0].arrive = "<img src=x>";
  evil.cost.currency = "<script>";
  evil.tips = Array(20).fill("tip");
  evil.warnings = Array(20).fill("w");
  const [p] = readPlans({ plans: [evil, evil, evil] });
  assert.equal(readPlans({ plans: [evil, evil, evil] }).length, 2); // max 2 plans
  assert.equal(p.days[0].stops[0].maps_url, null);
  assert.equal(p.days[0].stops[0].name.length, 120);
  assert.equal(p.days[0].stops[0].arrive, "");
  assert.equal(p.cost.currency, "INR");
  assert.equal(p.tips.length, 4);
  assert.equal(p.warnings.length, 5);
});

test("stops are capped at 10 in total across days", () => {
  const stop = (n) => ({ order: n, name: `S${n}`, arrive: "09:00", depart: "10:00" });
  const day = (d) => ({ day: d, end_time: "18:00", stops: Array.from({ length: 8 }, (_, i) => stop(i + 1)) });
  const p = normalizePlan({ plan_type: "cheapest", days: [day(1), day(2)], cost: {} });
  assert.equal(stopCount(p), 10);
});

test("formatters", () => {
  assert.equal(formatMinutes(85), "1 h 25 min");
  assert.equal(formatMinutes(40), "40 min");
  assert.equal(formatMinutes(120), "2 h");
  assert.equal(formatMinutes(null), "");
  assert.equal(formatKm(6.24), "6.2 km");
  assert.equal(formatKm(31.4), "31 km");
  assert.match(formatMoney(1388), /1,388/);
  assert.equal(formatMoney(null), "");
  assert.equal(trafficChipText({ level: "heavy", from: "17:00", to: "20:00" }), "Avoid 17:00–20:00");
  assert.equal(trafficChipText({ level: "moderate", from: "08:00", to: "10:00" }), "Busy 08:00–10:00");
  const leg = { mode: "DRIVE", distance_km: 6.2, duration_min: 25, duration_in_traffic_min: 32 };
  assert.match(legText(leg), /Drive · 6\.2 km · 32 min in traffic \(25 min without\)/);
  assert.match(legText({ mode: "WALK", distance_km: 1, duration_min: 12, duration_in_traffic_min: 12 }), /Walk · 1\.0 km · 12 min$/);
  assert.equal(modeOptionText({ mode: "TRANSIT", total_minutes: null, total_km: null, note: "" }), "Not available");
  assert.equal(modeOptionText({ mode: "DRIVE", total_minutes: 190, total_km: 31.4, note: "" }), "3 h 10 min · 31 km");
});

test("preview text", () => {
  assert.equal(previewText({ plans: real.plans }), "🗺️ Travel plan · 5 stops");
  assert.equal(previewText({}), "🗺️ Travel plan");
});

test("text fallback has the timeline and the estimate label, and no coordinates", () => {
  const text = formatTextPlan(real.plans);
  assert.match(text, /Cheapest plan/);
  assert.match(text, /Comfort plan/);
  assert.match(text, /Lunch:/);
  assert.match(text, /\(estimate\)/);
  assert.doesNotMatch(text, /latitude|longitude|lat=|lng=/i);
});

test("validateTripOptions", () => {
  const ok = { ...DEFAULT_TRIP_OPTIONS };
  assert.deepEqual(validateTripOptions(ok, "2026-10-11"), []);
  assert.ok(validateTripOptions({ ...ok, start_time: "" }, "2026-10-11").length);
  assert.ok(validateTripOptions({ ...ok, travelers: 0 }, "2026-10-11").length);
  assert.ok(validateTripOptions({ ...ok, travelers: 21 }, "2026-10-11").length);
  assert.ok(validateTripOptions({ ...ok, travelers: 1.5 }, "2026-10-11").length);
  assert.ok(validateTripOptions({ ...ok, date: "2020-01-01" }, "2026-10-11").length);
  assert.deepEqual(validateTripOptions({ ...ok, date: "2026-10-17" }, "2026-10-11"), []);
  assert.ok(validateTripOptions({ ...ok, entry_fees: { a: "abc" } }, "2026-10-11").length);
  assert.deepEqual(validateTripOptions({ ...ok, entry_fees: { a: "" } }, "2026-10-11"), []);
});

test("buildTripRequest matches the 4.8 contract", () => {
  const cards = [
    { place_id: "a", photo_indexes: [0, 2] },
    { place_id: "b", photo_indexes: [1] },
  ];
  const body = buildTripRequest(
    { ...DEFAULT_TRIP_OPTIONS, travelers: "3", start_text: "  Colaba, Mumbai ", entry_fees: { a: "100", b: "", c: "0" }, plan: "both", objective: "least_distance" },
    cards,
  );
  assert.deepEqual(body.place_ids, ["a", "b"]);
  assert.deepEqual(body.photo_indexes_by_place, { a: [0, 2], b: [1] });
  assert.equal(body.travelers, 3);
  assert.deepEqual(body.start, { text: "Colaba, Mumbai", place_id: null });
  assert.deepEqual(body.entry_fees, { a: 100 }); // empty and 0 dropped
  assert.deepEqual(body.variants, ["cheapest", "comfort"]);
  assert.equal(body.objective, "least_distance");
  assert.equal(body.date, null);
  assert.equal(body.return_to_start, false);
  assert.deepEqual(buildTripRequest({ ...DEFAULT_TRIP_OPTIONS, plan: "comfort" }, cards).variants, ["comfort"]);
  assert.equal(buildTripRequest({ ...DEFAULT_TRIP_OPTIONS }, cards).start, null); // no text -> no start
  assert.equal(buildTripRequest(DEFAULT_TRIP_OPTIONS, Array.from({ length: 12 }, (_, i) => ({ place_id: `p${i}` }))).place_ids.length, 10);
});

test("sanitizePlan whitelists fields: coordinates and unknown keys never reach the message", () => {
  const dirty = JSON.parse(JSON.stringify(real.plans[0]));
  dirty.lat = 19.07; dirty.origin = { lat: 1, lng: 2 };
  dirty.days[0].stops[0].latitude = 19.0;
  dirty.days[0].stops[0].leg_from_previous.polyline = "abc";
  dirty.cost.is_estimate = false; // cannot be turned off
  const clean = sanitizePlan(dirty);
  const json = JSON.stringify(clean);
  assert.doesNotMatch(json, /"lat"|"lng"|latitude|longitude|origin|polyline/);
  assert.equal(clean.cost.is_estimate, true);
  assert.equal(clean.attribution, "Google Maps");
  assert.deepEqual(Object.keys(clean.traffic_windows[0]).sort(), ["from", "label", "level", "note", "to"]);
});

test("real plans fit the size limit untouched; oversize payloads shrink mode_options first", () => {
  const r = preparePlansForSend(real.plans);
  assert.ok(r.fits && r.bytes <= MAX_PLAN_BYTES);
  assert.equal(r.bytes, byteLength(messagePayload(r.plans)));
  assert.equal(r.plans[0].mode_options.length, real.plans[0].mode_options.length); // nothing dropped when it fits

  const big = JSON.parse(JSON.stringify(real.plans));
  for (const p of big) p.mode_options = Array.from({ length: 4 }, (_, i) => ({ mode: "DRIVE", total_minutes: i, total_km: 1, note: "n".repeat(900) }));
  const small = preparePlansForSend(big, 14000);
  assert.ok(small.fits);
  assert.equal(small.plans[0].mode_options.length, 0);
  assert.ok(small.plans[0].tips.length > 0); // tips kept when dropping mode_options was enough
  assert.ok(preparePlansForSend(big, 500).fits === false); // impossible limit reported honestly
});
