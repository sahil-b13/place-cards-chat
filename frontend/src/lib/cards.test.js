import test from "node:test";
import assert from "node:assert/strict";
import { initGroups, needsDecision, cardsToSend, sanitizeCard, messagePayload } from "./cards.js";

const card = (id, extra = {}) => ({ place_id: id, name: id, photo_indexes: [0], reviews: [1, 2, 3, 4], nearby: [], ...extra });

test("ok groups are pre-confirmed, uncertain ones pending", () => {
  const g = initGroups([
    { photo_indexes: [0], status: "ok", card: card("a") },
    { photo_indexes: [1], status: "low_confidence", card: null, candidates: [{ place_id: "x" }] },
    { photo_indexes: [2], status: "not_found", card: null },
  ]);
  assert.deepEqual(g.map((x) => x.decision), ["confirmed", "pending", "pending"]);
  assert.equal(needsDecision(g), true);
});

test("skipped/pending groups produce no cards; all skipped -> empty", () => {
  const g = initGroups([{ photo_indexes: [0], status: "ok", card: card("a") }]);
  g[0].decision = "skipped";
  assert.equal(needsDecision(g), false);
  assert.deepEqual(cardsToSend(g), []);
});

test("groups ending on the same place are merged with sorted photo indexes", () => {
  const g = initGroups([
    { photo_indexes: [2], status: "ok", card: card("a") },
    { photo_indexes: [0, 1], status: "ok", card: card("a") },
  ]);
  const out = cardsToSend(g);
  assert.equal(out.length, 1);
  assert.deepEqual(out[0].photo_indexes, [0, 1, 2]);
});

test("sanitizeCard drops unknown fields (e.g. coordinates) and caps lists", () => {
  const out = sanitizeCard(card("a", { lat: 19.07, lng: 72.87, location: { latitude: 1 } }));
  assert.equal("lat" in out, false);
  assert.equal("lng" in out, false);
  assert.equal("location" in out, false);
  assert.equal(out.reviews.length, 3);
});

test("payload shape matches contract 4.6", () => {
  assert.deepEqual(messagePayload([1]), { cards: [1], version: 1 });
});
