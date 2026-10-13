import { useState } from "react";
import { resolvePlace } from "../lib/api";
import TripPlanOptions from "./TripPlanOptions.jsx";

export default function ReviewStep({ groups, setGroups, photos, hint, error, blocked, onBack, onSend, onSendPlain, trip }) {
  const update = (id, patch) => setGroups((gs) => gs.map((g) => (g.id === id ? { ...g, ...patch } : g)));
  const confirmed = groups.filter((g) => g.decision === "confirmed").length;
  const allMissing = groups.every((g) => !g.card && g.status === "not_found");
  // The travel plan needs at least one confirmed place; it is off (and its button hidden) otherwise.
  const canPlan = trip.cards.length > 0;
  const planOn = trip.on && canPlan;

  return (
    <div className="modal-body">
      {allMissing && (
        <p className="notice">No places were found. You can type a place name for a photo group, or send the photos without place info.</p>
      )}
      <div className="groups">
        {groups.map((g) => (
          <GroupReview key={g.id} g={g} photos={photos} hint={hint} update={update} />
        ))}
      </div>

      <section className="trip-toggle">
        <label className={`toggle-row ${canPlan ? "" : "disabled"}`}>
          <input type="checkbox" checked={planOn} disabled={!canPlan} onChange={(e) => trip.setOn(e.target.checked)} />
          <span><strong>🗺️ Make a travel plan</strong> <span className="muted small">(optional)</span></span>
        </label>
        {!canPlan && <p className="muted small">Confirm at least one place to enable this.</p>}
        {planOn && (
          <TripPlanOptions options={trip.options} onChange={trip.setOptions} places={trip.cards}
                           errors={trip.errors} todayIso={trip.todayIso} />
        )}
      </section>

      {error && <p className="error">{error}</p>}
      <div className="modal-actions">
        <button className="link" onClick={onBack}>← Back</button>
        <button className="secondary" onClick={onSendPlain}>Send photos without place info</button>
        {planOn ? (
          <button className="primary" disabled={blocked || trip.errors.length > 0} onClick={trip.onPlan}
                  title={blocked ? "Confirm, change or skip each highlighted group first" : ""}>
            Preview travel plan →
          </button>
        ) : (
          <button className="primary" disabled={blocked} onClick={onSend}
                  title={blocked ? "Confirm, change or skip each highlighted group first" : ""}>
            {confirmed ? `Send photos + ${confirmed} place card${confirmed > 1 ? "s" : ""}` : "Send photos"}
          </button>
        )}
      </div>
      {blocked && <p className="muted small">Highlighted groups need a decision: confirm, change, or skip.</p>}
    </div>
  );
}

function GroupReview({ g, photos, hint, update }) {
  const [changing, setChanging] = useState(g.status !== "ok" && !g.card);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function run(payload) {
    setBusy(true);
    setMsg("");
    try {
      const r = await resolvePlace(payload);
      if (r.status === "ok" && r.card) {
        update(g.id, { card: r.card, status: "ok", candidates: [], decision: "confirmed" });
        setChanging(false);
      } else if (r.status === "low_confidence" && r.candidates?.length) {
        update(g.id, { candidates: r.candidates, status: "low_confidence" });
        setMsg("Several matches — pick one:");
      } else {
        setMsg("No match found. Try a more specific name or add a city.");
      }
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  }

  const attention = g.decision === "pending";
  return (
    <div className={`group ${attention ? "attention" : ""} ${g.decision === "skipped" ? "skipped" : ""}`}>
      <div className="group-photos">
        {g.photo_indexes.map((i) => photos[i] && <img key={i} src={photos[i].url} alt={`Photo ${i + 1}`} />)}
        <span className="muted small">Photo{g.photo_indexes.length > 1 ? "s" : ""} {g.photo_indexes.map((i) => i + 1).join(", ")}</span>
      </div>

      {g.card && (
        <div className="card-preview">
          <div className="cp-title">
            <strong>{g.card.name}</strong>
            <span className="chip">{g.card.category}</span>
            {g.card.source === "user" && <span className="chip alt">picked by you</span>}
            {g.status !== "ok" ? null : <span className={`chip conf-${g.card.confidence}`}>{g.card.confidence} confidence</span>}
          </div>
          <div className="small">
            {g.card.rating != null && <>★ {g.card.rating} ({g.card.rating_count}) · </>}
            {g.card.price_label && <>{g.card.price_label} · </>}
            {g.card.open_now != null && <>{g.card.open_now ? "Open now" : "Closed"} · </>}
            {g.card.area}
          </div>
          {g.card.summary && <div className="small muted">{g.card.summary}</div>}
          <div className="small muted">{g.card.address}</div>
        </div>
      )}
      {!g.card && (
        <p className="small">
          {g.status === "low_confidence" ? "We're not sure which place this is." : "Couldn't identify a place in this photo."}
        </p>
      )}

      {g.decision === "skipped" && <p className="small muted">No place info for these photos.</p>}

      {changing && (
        <div className="change-box">
          {g.candidates.length > 0 && (
            <ul className="candidates">
              {g.candidates.map((c) => (
                <li key={c.place_id}>
                  <button disabled={busy} onClick={() => run({ place_id: c.place_id })}>
                    <strong>{c.name}</strong><span className="small muted"> {c.address}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="row">
            <input className="text-input" placeholder="Type the place name" value={query}
                   onChange={(e) => setQuery(e.target.value)}
                   onKeyDown={(e) => e.key === "Enter" && query.trim() && run({ query: query.trim(), hint: hint || null })} />
            <button className="secondary" disabled={busy || !query.trim()}
                    onClick={() => run({ query: query.trim(), hint: hint || null })}>
              {busy ? "Searching…" : "Search"}
            </button>
          </div>
          {msg && <p className="small">{msg}</p>}
        </div>
      )}

      <div className="group-actions">
        {g.card && g.decision !== "confirmed" && (
          <button className="primary sm" onClick={() => update(g.id, { decision: "confirmed" })}>Confirm</button>
        )}
        {g.decision === "confirmed" && <span className="ok-tag">✓ Confirmed</span>}
        <button className="secondary sm" onClick={() => setChanging((c) => !c)}>{changing ? "Cancel change" : "Change"}</button>
        {g.decision !== "skipped" && (
          <button className="secondary sm" onClick={() => update(g.id, { decision: "skipped" })}>Skip place info</button>
        )}
        {g.decision === "skipped" && g.card && (
          <button className="secondary sm" onClick={() => update(g.id, { decision: "confirmed" })}>Use it after all</button>
        )}
      </div>
    </div>
  );
}
