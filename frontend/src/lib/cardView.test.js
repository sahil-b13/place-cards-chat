import test from "node:test";
import assert from "node:assert/strict";
import {
  safeUrl, mapsUrlFor, normalizeCard, readCards, photoLabel, stars, formatCount, formatDistance,
  previewText, formatTextCards, PLACE_CARDS_TYPE,
} from "./cardView.js";

const full = {
  place_id: "p1", name: "Cafe Leopold", category: "restaurant", is_restaurant: true,
  summary: "Iconic cafe.", address: "Colaba Causeway, Mumbai", area: "Colaba", rating: 4.4, rating_count: 12400,
  price_label: "₹₹", open_now: true, hours_today: "8 AM – 12 AM",
  reviews: [{ author: "A", rating: 5, text: "Great", when: "a week ago" }, { author: "B", rating: 4, text: "" }],
  nearby: [], website: "https://leopold.example", maps_url: "https://maps.google.com/?cid=1",
  photo_indexes: [0, 2], confidence: "high", source: "vision", attribution: "Google Maps",
};

test("type constant matches the plan", () => assert.equal(PLACE_CARDS_TYPE, "place_cards"));

test("safeUrl allows only http(s)", () => {
  assert.equal(safeUrl("https://a.com/x"), "https://a.com/x");
  assert.equal(safeUrl("javascript:alert(1)"), null);
  assert.equal(safeUrl("data:text/html,hi"), null);
  assert.equal(safeUrl("not a url"), null);
  assert.equal(safeUrl(42), null);
});

test("maps url falls back to a name+address search link", () => {
  assert.match(mapsUrlFor({ name: "A B", address: "C" }), /google\.com\/maps\/search\/\?api=1&query=A%20B%2C%20C/);
  assert.equal(mapsUrlFor({ maps_url: "javascript:x", name: "", address: "" }), null);
});

test("normalizeCard drops empty reviews and clamps lists/text", () => {
  const c = normalizeCard({ ...full, name: "x".repeat(500), reviews: Array(9).fill({ text: "t" }), nearby: Array(9).fill({ name: "n" }) });
  assert.equal(c.name.length, 120);
  assert.equal(c.reviews.length, 3);
  assert.equal(c.nearby.length, 3);
  assert.equal(normalizeCard(full).reviews.length, 1);
});

test("normalizeCard rejects garbage and sanitises unsafe links", () => {
  assert.equal(normalizeCard(null), null);
  assert.equal(normalizeCard({ name: "" }), null);
  const c = normalizeCard({ name: "X", website: "javascript:alert(1)", category: "weird", rating: "5" });
  assert.equal(c.website, null);
  assert.equal(c.category, "other");
  assert.equal(c.rating, null);
});

test("readCards handles missing/bad payloads and caps at 10", () => {
  assert.deepEqual(readCards(undefined), []);
  assert.deepEqual(readCards({ cards: "nope" }), []);
  assert.equal(readCards({ cards: Array(15).fill(full) }).length, 10);
  assert.equal(readCards({ cards: [full, { bad: 1 }] }).length, 1);
});

test("photoLabel is 1-based and pluralised", () => {
  assert.equal(photoLabel([0]), "Photo 1");
  assert.equal(photoLabel([0, 2]), "Photos 1, 3");
  assert.equal(photoLabel([]), "");
});

test("stars / counts / distance formatting", () => {
  assert.equal(stars(4.4), "★★★★☆");
  assert.equal(stars(9), "★★★★★");
  assert.equal(stars(null), "");
  assert.equal(formatCount(950), "950");
  assert.equal(formatCount(1200), "1.2k");
  assert.equal(formatCount(12400), "12k");
  assert.equal(formatDistance(150), "150 m");
  assert.equal(formatDistance(1500), "1.5 km");
});

test("preview text", () => {
  assert.equal(previewText({ cards: [full] }), "📍 Cafe Leopold");
  assert.equal(previewText({ cards: [full, full] }), "📍 2 places");
  assert.equal(previewText(undefined), "📍 Place info");
});

test("text fallback is readable and contains no coordinates", () => {
  const t = formatTextCards([full]);
  assert.match(t, /Cafe Leopold — restaurant/);
  assert.match(t, /★ 4.4 \(12k\) · ₹₹ · Open now/);
  assert.match(t, /Maps: https:\/\/maps\.google\.com/);
  assert.match(t, /Photos 1, 3/);
  assert.doesNotMatch(t, /"lat"|"lng"|latitude|longitude/i);
});
