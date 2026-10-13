// Pure helpers for the OUTGOING side of the travel plan (Phase 6): options form state, request
// building/validation, whitelisting and size-limiting of the `trip_plan` custom message payload.

export const DEFAULT_TRIP_OPTIONS = {
  start_time: "08:00",
  date: "",
  start_text: "",
  travelers: 2,
  objective: "least_time", // least_time | least_distance
  plan: "both", // cheapest | comfort | both
  entry_fees: {}, // { place_id: "100" } per person, optional
};

// Mirrors the backend limits; the backend re-validates everything.
export const MAX_PLAN_BYTES = 14000; // same guess as backend costs.json: verify CometChat's limit

export function validateTripOptions(o, todayIso) {
  const errors = [];
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(o.start_time || "")) errors.push("Choose a start time.");
  const t = Number(o.travelers);
  if (!Number.isInteger(t) || t < 1 || t > 20) errors.push("Travelers must be a whole number from 1 to 20.");
  if (o.date) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(o.date)) errors.push("Date is not valid.");
    else if (todayIso && o.date < todayIso) errors.push("Pick today or a future date (traffic estimates need a future time).");
  }
  if ((o.start_text || "").length > 120) errors.push("Start place is too long.");
  for (const [id, v] of Object.entries(o.entry_fees || {})) {
    if (v !== "" && v != null && !(Number.isFinite(Number(v)) && Number(v) >= 0)) errors.push("Entry fees must be numbers (0 or more).");
    if (!id) errors.push("Entry fee is missing a place.");
  }
  return [...new Set(errors)];
}

// options + cards to send -> body for POST /api/trip-plan (Section 4.8). Start is typed text only.
export function buildTripRequest(o, cards) {
  const entry_fees = {};
  for (const [id, v] of Object.entries(o.entry_fees || {})) {
    const n = Number(v);
    if (v !== "" && Number.isFinite(n) && n > 0) entry_fees[id] = n;
  }
  const photo_indexes_by_place = {};
  for (const c of cards) photo_indexes_by_place[c.place_id] = c.photo_indexes || [];
  return {
    place_ids: cards.map((c) => c.place_id).slice(0, 10),
    photo_indexes_by_place,
    start_time: o.start_time,
    date: o.date || null,
    start: o.start_text.trim() ? { text: o.start_text.trim().slice(0, 120), place_id: null } : null,
    return_to_start: false,
    travelers: Number(o.travelers),
    objective: o.objective === "least_distance" ? "least_distance" : "least_time",
    variants: o.plan === "both" ? ["cheapest", "comfort"] : [o.plan === "comfort" ? "comfort" : "cheapest"],
    entry_fees,
  };
}

const LEG_KEYS = ["mode", "distance_km", "duration_min", "duration_in_traffic_min"];
const STOP_KEYS = ["order", "place_id", "name", "category", "arrive", "depart", "visit_minutes", "photo_indexes", "maps_url"];
const LUNCH_KEYS = ["after_stop_order", "name", "place_id", "arrive", "minutes", "price_label", "rating", "maps_url"];
const COST_KEYS = ["currency", "travel", "food", "entry", "total", "per_person", "assumptions", "is_estimate"];
const PLAN_KEYS = [
  "version", "plan_type", "date", "start_time", "start_label", "travelers", "objective",
  "traffic_windows", "mode_options", "tips", "warnings", "attribution",
];

const pick = (obj, keys) => {
  const out = {};
  if (!obj) return out;
  for (const k of keys) if (obj[k] !== undefined) out[k] = obj[k];
  return out;
};

// Whitelist the contract fields (Section 4.7) so nothing unexpected (e.g. coordinates) can reach a chat message.
export function sanitizePlan(plan) {
  const out = pick(plan, PLAN_KEYS);
  out.version = 1;
  out.days = (plan.days || []).map((d) => ({
    day: d.day,
    stops: (d.stops || []).slice(0, 10).map((s) => ({
      ...pick(s, STOP_KEYS),
      leg_from_previous: s.leg_from_previous ? pick(s.leg_from_previous, LEG_KEYS) : null,
    })),
    lunch: d.lunch ? pick(d.lunch, LUNCH_KEYS) : null,
    end_time: d.end_time,
  }));
  out.cost = { ...pick(plan.cost, COST_KEYS), is_estimate: true };
  out.tips = (out.tips || []).slice(0, 4);
  out.warnings = (out.warnings || []).slice(0, 5);
  out.traffic_windows = (out.traffic_windows || []).map((w) => pick(w, ["label", "from", "to", "level", "note"]));
  out.mode_options = (out.mode_options || []).map((m) => pick(m, ["mode", "total_minutes", "total_km", "note"]));
  return out;
}

export const byteLength = (obj) => new TextEncoder().encode(JSON.stringify(obj)).length;

export function messagePayload(plans) {
  return { plans, version: 1 };
}

// Sanitize, then shrink until the payload fits: drop mode_options first, then shorten notes, then tips.
export function preparePlansForSend(plans, maxBytes = MAX_PLAN_BYTES) {
  let list = plans.map(sanitizePlan);
  const fits = () => byteLength(messagePayload(list)) <= maxBytes;
  const steps = [
    (p) => ({ ...p, mode_options: [] }),
    (p) => ({
      ...p,
      traffic_windows: p.traffic_windows.map((w) => ({ ...w, note: (w.note || "").slice(0, 40) })),
      cost: { ...p.cost, assumptions: p.cost.assumptions.map((a) => a.slice(0, 60)) },
    }),
    (p) => ({ ...p, tips: [] }),
  ];
  for (const step of steps) {
    if (fits()) break;
    list = list.map(step);
  }
  return { plans: list, fits: fits(), bytes: byteLength(messagePayload(list)) };
}
