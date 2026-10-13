import { API_BASE_URL } from "../cometchat/config";

async function request(path, init = {}, timeoutMs = 60000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  // An https page cannot call a plain-http API (browsers block it as mixed content).
  const isLocal = /^http:\/\/(localhost|127\.0\.0\.1)/.test(API_BASE_URL);
  if (typeof location !== "undefined" && location.protocol === "https:" && API_BASE_URL.startsWith("http:") && !isLocal) {
    throw new Error("VITE_API_BASE_URL must be an https:// URL when the app is served over https.");
  }
  let res;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { ...init, signal: ctrl.signal });
  } catch (e) {
    if (e?.name === "AbortError") throw new Error("The place-info service took too long to respond.");
    throw new Error(`Can't reach the place-info service at ${API_BASE_URL}. Is the backend running?`);
  } finally {
    clearTimeout(timer);
  }
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) throw new Error(body?.error?.message || `Place-info service error (${res.status})`);
  return body;
}

export function health() {
  return request("/api/health", {}, 8000);
}

// items: [{ file: File (resized JPEG), gps: {lat,lng}|null }]
export async function analyzePhotos(items, globalHint) {
  const form = new FormData();
  const meta = [];
  items.forEach((it, index) => {
    form.append("images", it.file, it.file.name);
    if (it.gps) meta.push({ index, lat: it.gps.lat, lng: it.gps.lng });
  });
  if (meta.length) form.append("meta", JSON.stringify(meta));
  if (globalHint?.trim()) form.append("global_hint", globalHint.trim());
  const data = await request("/api/place-cards", { method: "POST", body: form }, 90000);
  return data.results || [];
}

// { query, hint } or { place_id }  ->  { status, card, candidates }
export function resolvePlace(payload) {
  return request("/api/place-cards/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// Section 4.8 body -> { plans, status: "ok" | "partial" | "unsupported", warnings }
// Routes calls (traffic slots, modes) can take a while, so the timeout is generous.
export function planTrip(payload) {
  return request("/api/trip-plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }, 120000);
}
