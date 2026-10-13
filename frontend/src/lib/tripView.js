// Pure helpers for RENDERING trip plans (Phase 6). No React, no CometChat imports -> unit-testable.
// Incoming `trip_plan` messages are untrusted (any client can send one): everything is validated and
// clamped here, links must be http(s), and the UI only ever renders values as React text.
import { safeUrl, photoLabel } from "./cardView.js";

export const TRIP_PLAN_TYPE = "trip_plan";
const MAX_PLANS = 2;
const MAX_DAYS = 5;
const MAX_STOPS = 10;
const PLAN_TYPES = ["cheapest", "comfort"];
const MODES = ["DRIVE", "TRANSIT", "WALK", "TWO_WHEELER"];
const LEVELS = ["heavy", "moderate", "light"];

const str = (v, max) => (typeof v === "string" ? v.trim().slice(0, max) : "");
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const int = (v) => (num(v) == null ? null : Math.round(v));
const hhmm = (v) => (typeof v === "string" && /^([01]\d|2[0-3]):[0-5]\d$/.test(v) ? v : "");
const list = (v, max) => (Array.isArray(v) ? v.slice(0, max) : []);

export const MODE_LABEL = { DRIVE: "Drive", TRANSIT: "Transit", WALK: "Walk", TWO_WHEELER: "Two-wheeler" };
export const MODE_ICON = { DRIVE: "🚗", TRANSIT: "🚆", WALK: "🚶", TWO_WHEELER: "🛵" };
export const PLAN_LABEL = { cheapest: "Cheapest", comfort: "Comfort" };

function normalizeLeg(raw) {
  if (!raw || typeof raw !== "object" || !MODES.includes(raw.mode)) return null;
  return {
    mode: raw.mode,
    distance_km: num(raw.distance_km),
    duration_min: int(raw.duration_min),
    duration_in_traffic_min: int(raw.duration_in_traffic_min),
  };
}

function normalizeStop(raw) {
  if (!raw || typeof raw !== "object") return null;
  const name = str(raw.name, 120);
  if (!name) return null;
  return {
    order: int(raw.order),
    place_id: str(raw.place_id, 200),
    name,
    category: str(raw.category, 20) || "other",
    arrive: hhmm(raw.arrive),
    depart: hhmm(raw.depart),
    visit_minutes: int(raw.visit_minutes),
    photo_indexes: list(raw.photo_indexes, 10).filter((i) => Number.isInteger(i) && i >= 0),
    maps_url: safeUrl(raw.maps_url),
    leg: normalizeLeg(raw.leg_from_previous),
  };
}

function normalizeLunch(raw) {
  if (!raw || typeof raw !== "object") return null;
  const name = str(raw.name, 120);
  if (!name) return null;
  return {
    after_stop_order: int(raw.after_stop_order),
    name,
    arrive: hhmm(raw.arrive),
    minutes: int(raw.minutes),
    price_label: str(raw.price_label, 8),
    rating: num(raw.rating),
    maps_url: safeUrl(raw.maps_url),
  };
}

export function normalizePlan(raw) {
  if (!raw || typeof raw !== "object" || !PLAN_TYPES.includes(raw.plan_type)) return null;
  let budget = MAX_STOPS;
  const days = list(raw.days, MAX_DAYS)
    .map((d) => {
      if (!d || typeof d !== "object") return null;
      const stops = list(d.stops, MAX_STOPS).map(normalizeStop).filter(Boolean).slice(0, budget);
      budget -= stops.length;
      return stops.length ? { day: int(d.day), stops, lunch: normalizeLunch(d.lunch), end_time: hhmm(d.end_time) } : null;
    })
    .filter(Boolean);
  if (!days.length) return null;
  const cost = raw.cost && typeof raw.cost === "object" ? raw.cost : {};
  return {
    plan_type: raw.plan_type,
    date: /^\d{4}-\d{2}-\d{2}$/.test(raw.date) ? raw.date : "",
    start_time: hhmm(raw.start_time),
    start_label: str(raw.start_label, 120),
    travelers: int(raw.travelers),
    objective: raw.objective === "least_distance" ? "least_distance" : "least_time",
    days,
    traffic_windows: list(raw.traffic_windows, 8)
      .map((w) => ({
        label: str(w?.label, 40),
        from: hhmm(w?.from),
        to: hhmm(w?.to),
        level: LEVELS.includes(w?.level) ? w.level : "light",
        note: str(w?.note, 120),
      }))
      .filter((w) => w.from && w.to),
    mode_options: list(raw.mode_options, 4)
      .filter((m) => m && MODES.includes(m.mode))
      .map((m) => ({ mode: m.mode, total_minutes: int(m.total_minutes), total_km: num(m.total_km), note: str(m.note, 80) })),
    cost: {
      currency: /^[A-Z]{3}$/.test(cost.currency) ? cost.currency : "INR",
      travel: int(cost.travel),
      food: int(cost.food),
      entry: int(cost.entry), // null = "not included"
      total: int(cost.total),
      per_person: int(cost.per_person),
      assumptions: list(cost.assumptions, 8).map((a) => str(a, 120)).filter(Boolean),
    },
    tips: list(raw.tips, 4).map((t) => str(t, 160)).filter(Boolean),
    warnings: list(raw.warnings, 5).map((w) => str(w, 160)).filter(Boolean),
    attribution: str(raw.attribution, 40) || "Google Maps",
  };
}

// customData of a trip_plan message -> valid, clamped plans (max 2)
export function readPlans(customData) {
  return list(customData?.plans, MAX_PLANS).map(normalizePlan).filter(Boolean);
}

export const stopCount = (plan) => plan.days.reduce((n, d) => n + d.stops.length, 0);

// 85 -> "1 h 25 min", 40 -> "40 min", null -> ""
export function formatMinutes(m) {
  if (m == null || m < 0) return "";
  const h = Math.floor(m / 60);
  const r = m % 60;
  if (!h) return `${r} min`;
  return r ? `${h} h ${r} min` : `${h} h`;
}

export function formatKm(km) {
  if (km == null) return "";
  return km < 10 ? `${km.toFixed(1)} km` : `${Math.round(km)} km`;
}

export function formatMoney(amount, currency = "INR") {
  if (amount == null) return "";
  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 0 }).format(amount);
  } catch {
    return `${currency} ${amount}`;
  }
}

// "2026-10-17" -> "Sat, 17 Oct" (UTC so the calendar day never shifts with the viewer's timezone)
export function formatPlanDate(date) {
  if (!date) return "";
  const d = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
}

// Leg line: "🚗 Drive · 6.2 km · 25 min (32 min in traffic)"
export function legText(leg) {
  if (!leg) return "";
  const base = leg.duration_min;
  const traffic = leg.duration_in_traffic_min;
  const parts = [`${MODE_ICON[leg.mode]} ${MODE_LABEL[leg.mode]}`];
  if (leg.distance_km != null) parts.push(formatKm(leg.distance_km));
  const time = traffic != null ? traffic : base;
  if (time != null) {
    const showStatic = leg.mode === "DRIVE" && base != null && traffic != null && traffic > base;
    parts.push(showStatic ? `${formatMinutes(traffic)} in traffic (${formatMinutes(base)} without)` : formatMinutes(time));
  }
  return parts.join(" · ");
}

// Chip text for a traffic window. Heavy windows say "avoid".
export function trafficChipText(w) {
  const span = `${w.from}–${w.to}`;
  if (w.level === "heavy") return `Avoid ${span}`;
  if (w.level === "moderate") return `Busy ${span}`;
  return `Light ${span}`;
}

// Does the lunch for this day belong after this stop?
export const lunchAfter = (day, stop) => Boolean(day.lunch && day.lunch.after_stop_order === stop.order);

export function modeOptionText(m) {
  if (m.total_minutes == null) return m.note || "Not available";
  return [formatMinutes(m.total_minutes), m.total_km != null ? formatKm(m.total_km) : "", m.note].filter(Boolean).join(" · ");
}

// Conversation-list preview.
export function previewText(customData) {
  const plans = readPlans(customData);
  if (!plans.length) return "🗺️ Travel plan";
  const n = stopCount(plans[0]);
  return `🗺️ Travel plan · ${n} stop${n === 1 ? "" : "s"}`;
}

// FALLBACK_TEXT_CARDS: the plan as one plain-text message (no coordinates, ever).
export function formatTextPlan(rawPlans) {
  const plans = readPlans({ plans: rawPlans });
  return plans
    .map((p) => {
      const lines = [
        `🗺️ ${PLAN_LABEL[p.plan_type]} plan · ${[formatPlanDate(p.date), p.start_time && `start ${p.start_time}`, p.travelers && `${p.travelers} traveler${p.travelers === 1 ? "" : "s"}`].filter(Boolean).join(" · ")}`,
      ];
      for (const d of p.days) {
        if (p.days.length > 1) lines.push(`— Day ${d.day} —`);
        for (const s of d.stops) {
          if (s.leg) lines.push(`   ${legText(s.leg)}`);
          lines.push(`${s.order}. ${s.name} ${s.arrive}–${s.depart}`);
          if (lunchAfter(d, s)) lines.push(`   🍽 Lunch: ${d.lunch.name} ${d.lunch.arrive} (${formatMinutes(d.lunch.minutes)})`);
        }
        if (d.end_time) lines.push(`Finish ~${d.end_time}`);
      }
      for (const w of p.traffic_windows.filter((x) => x.level !== "light")) lines.push(`⚠ ${trafficChipText(w)}`);
      if (p.cost.total != null) {
        lines.push(`Estimated cost: ${formatMoney(p.cost.total, p.cost.currency)} total · ${formatMoney(p.cost.per_person, p.cost.currency)} per person (estimate)`);
      }
      for (const w of p.warnings) lines.push(`• ${w}`);
      lines.push(p.attribution);
      return lines.join("\n");
    })
    .join("\n\n");
}

export { photoLabel };
