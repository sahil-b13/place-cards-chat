// Pure helpers for the review step and the outgoing custom message (no React, no CometChat).

const CARD_KEYS = [
  "place_id", "name", "category", "is_restaurant", "summary", "address", "area", "rating",
  "rating_count", "price_level", "price_label", "open_now", "hours_today", "reviews", "nearby",
  "website", "maps_url", "photo_indexes", "confidence", "source", "attribution",
];

// Whitelist the contract fields so nothing unexpected (e.g. coordinates) ever reaches a chat message.
export function sanitizeCard(card) {
  const out = {};
  for (const k of CARD_KEYS) if (card[k] !== undefined) out[k] = card[k];
  out.reviews = (out.reviews || []).slice(0, 3);
  out.nearby = (out.nearby || []).slice(0, 3);
  return out;
}

export function initGroups(results) {
  return results.map((r, i) => ({
    id: `g${i}`,
    photo_indexes: r.photo_indexes,
    status: r.status,
    card: r.card || null,
    candidates: r.candidates || [],
    // clean matches are pre-confirmed; anything uncertain must be decided by the sender
    decision: r.status === "ok" && r.card ? "confirmed" : "pending",
  }));
}

export const needsDecision = (groups) => groups.some((g) => g.decision === "pending");

// Confirmed groups -> cards; groups that ended on the same place_id are merged.
export function cardsToSend(groups) {
  const byId = new Map();
  for (const g of groups) {
    if (g.decision !== "confirmed" || !g.card) continue;
    const prev = byId.get(g.card.place_id);
    const idx = new Set([...(prev?.photo_indexes || []), ...g.photo_indexes]);
    byId.set(g.card.place_id, { ...g.card, photo_indexes: [...idx].sort((a, b) => a - b) });
  }
  return [...byId.values()].map(sanitizeCard);
}

export function messagePayload(cards) {
  return { cards, version: 1 };
}
