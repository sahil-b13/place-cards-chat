// Pure helpers for RENDERING place cards (Phase 4). No React, no CometChat imports -> unit-testable.
// Incoming messages are untrusted input (any client can send a "place_cards" message), so everything
// is validated/clamped here and only ever rendered as React text (never as HTML).

export const PLACE_CARDS_TYPE = "place_cards";
const MAX_CARDS = 10;
const CATEGORIES = ["restaurant", "landmark", "cafe", "park", "other"];

const str = (v, max) => (typeof v === "string" ? v.trim().slice(0, max) : "");
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

// Only http(s) links are ever rendered as <a href>. Blocks javascript:, data:, etc.
export function safeUrl(value) {
  if (typeof value !== "string") return null;
  try {
    const u = new URL(value.trim());
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

export function mapsUrlFor(card) {
  const direct = safeUrl(card.maps_url);
  if (direct) return direct;
  const q = [card.name, card.address].filter(Boolean).join(", ");
  return q ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}` : null;
}

export function normalizeCard(raw) {
  if (!raw || typeof raw !== "object") return null;
  const name = str(raw.name, 120);
  if (!name) return null;
  const category = CATEGORIES.includes(raw.category) ? raw.category : "other";
  const reviews = (Array.isArray(raw.reviews) ? raw.reviews : [])
    .map((r) => ({
      author: str(r?.author, 60) || "Google user",
      rating: num(r?.rating),
      text: str(r?.text, 200),
      when: str(r?.when, 40),
    }))
    .filter((r) => r.text)
    .slice(0, 3);
  const nearby = (Array.isArray(raw.nearby) ? raw.nearby : [])
    .map((n) => ({ name: str(n?.name, 80), rating: num(n?.rating), distance_m: num(n?.distance_m) }))
    .filter((n) => n.name)
    .slice(0, 3);
  const photo_indexes = (Array.isArray(raw.photo_indexes) ? raw.photo_indexes : [])
    .filter((i) => Number.isInteger(i) && i >= 0)
    .slice(0, 10);
  return {
    place_id: str(raw.place_id, 200),
    name,
    category,
    is_restaurant: raw.is_restaurant === true || category === "restaurant",
    summary: str(raw.summary, 200),
    address: str(raw.address, 200),
    area: str(raw.area, 80),
    rating: num(raw.rating),
    rating_count: num(raw.rating_count),
    price_label: str(raw.price_label, 8),
    open_now: typeof raw.open_now === "boolean" ? raw.open_now : null,
    hours_today: str(raw.hours_today, 60),
    reviews,
    nearby,
    website: safeUrl(raw.website),
    maps_url: mapsUrlFor(raw),
    photo_indexes,
    confidence: ["high", "medium", "low"].includes(raw.confidence) ? raw.confidence : null,
    source: str(raw.source, 10),
    attribution: str(raw.attribution, 40) || "Google Maps",
  };
}

// Takes the `customData` of a place_cards message -> list of valid, clamped cards.
export function readCards(customData) {
  const list = Array.isArray(customData?.cards) ? customData.cards : [];
  return list.slice(0, MAX_CARDS).map(normalizeCard).filter(Boolean);
}

// "Photo 1, 3" (indexes are 0-based in the payload, 1-based for humans). "" when unknown.
export function photoLabel(indexes) {
  if (!indexes?.length) return "";
  return `Photo${indexes.length > 1 ? "s" : ""} ${indexes.map((i) => i + 1).join(", ")}`;
}

// 4.4 -> "★★★★☆" (rounded to nearest whole star, clamped 0-5)
export function stars(rating) {
  if (rating == null) return "";
  const n = Math.max(0, Math.min(5, Math.round(rating)));
  return "★".repeat(n) + "☆".repeat(5 - n);
}

export function formatCount(n) {
  if (n == null) return "";
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "")}k` : String(n);
}

export function formatDistance(m) {
  if (m == null) return "";
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
}

// Short preview for the conversations list.
export function previewText(customData) {
  const cards = readCards(customData);
  if (!cards.length) return "📍 Place info";
  return cards.length === 1 ? `📍 ${cards[0].name}` : `📍 ${cards.length} places`;
}

// FALLBACK_TEXT_CARDS: one plain-text message with all cards (used when the custom bubble can't be used).
export function formatTextCards(cards) {
  const blocks = cards.map((raw) => {
    const c = normalizeCard(raw);
    if (!c) return "";
    const meta = [
      c.rating != null ? `★ ${c.rating}${c.rating_count != null ? ` (${formatCount(c.rating_count)})` : ""}` : "",
      c.price_label,
      c.open_now != null ? (c.open_now ? "Open now" : "Closed") : "",
    ].filter(Boolean).join(" · ");
    const lines = [
      `📍 ${c.name} — ${c.category}`,
      meta,
      c.summary,
      c.address,
      c.website ? `Website: ${c.website}` : "",
      c.maps_url ? `Maps: ${c.maps_url}` : "",
      c.photo_indexes.length ? `(${photoLabel(c.photo_indexes)})` : "",
    ].filter(Boolean);
    return lines.join("\n");
  });
  return blocks.filter(Boolean).join("\n\n");
}
