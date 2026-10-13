import { useState } from "react";
import {
  readPlans, PLAN_LABEL, formatMinutes, formatMoney, formatPlanDate, legText, trafficChipText,
  lunchAfter, modeOptionText, photoLabel, MODE_ICON, MODE_LABEL,
} from "../lib/tripView";

// Renders the customData of a `trip_plan` message (also used for the sender's preview): a vertical
// timeline with Cheapest/Comfort tabs. Same bubble for sender and receiver. Text only, never HTML.
export default function TripPlanBubble({ customData }) {
  const plans = readPlans(customData);
  const [active, setActive] = useState(0);
  if (!plans.length) return <div className="tp-bubble tp-empty">🗺️ Travel plan is unavailable for this message.</div>;
  const plan = plans[Math.min(active, plans.length - 1)];
  return (
    <div className="tp-bubble">
      {plans.length > 1 && (
        <div className="tp-tabs" role="tablist" aria-label="Plan type">
          {plans.map((p, i) => (
            <button key={p.plan_type} type="button" role="tab" aria-selected={i === active}
                    className={i === active ? "active" : ""} onClick={() => setActive(i)}>
              {PLAN_LABEL[p.plan_type]} · {formatMoney(p.cost.per_person, p.cost.currency)} pp
            </button>
          ))}
        </div>
      )}
      <Plan plan={plan} />
    </div>
  );
}

function Plan({ plan }) {
  const [showAssumptions, setShowAssumptions] = useState(false);
  const [showModes, setShowModes] = useState(false);
  const c = plan.cost;
  const multiDay = plan.days.length > 1;

  return (
    <article className="tp-plan">
      <header className="tp-head">
        <div>
          <h3 className="tp-title">{PLAN_LABEL[plan.plan_type]} day plan</h3>
          <div className="tp-sub">
            {[formatPlanDate(plan.date), plan.start_time && `Start ${plan.start_time}`, plan.travelers && `${plan.travelers} traveler${plan.travelers === 1 ? "" : "s"}`]
              .filter(Boolean).join(" · ")}
          </div>
          {plan.start_label && <div className="tp-sub">From {plan.start_label}</div>}
        </div>
        <span className="tp-est">Estimates</span>
      </header>

      {plan.warnings.length > 0 && (
        <ul className="tp-warnings">{plan.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}</ul>
      )}

      {plan.days.map((d) => (
        <section key={d.day} className="tp-day" aria-label={multiDay ? `Day ${d.day}` : "Timeline"}>
          {multiDay && <h4 className="tp-day-title">Day {d.day}</h4>}
          <ol className="tp-timeline">
            {d.stops.map((s) => (
              <li key={`${d.day}-${s.order}`} className="tp-item">
                {s.leg && <div className="tp-leg">{legText(s.leg)}</div>}
                <div className="tp-stop">
                  <span className="tp-dot" aria-hidden="true">{s.order}</span>
                  <div className="tp-stop-body">
                    <div className="tp-stop-name" title={s.name}>{s.name}</div>
                    <div className="tp-stop-time">
                      {s.arrive}–{s.depart}
                      {s.visit_minutes != null && <span className="tp-muted"> · {formatMinutes(s.visit_minutes)} there</span>}
                      {s.photo_indexes.length > 0 && <span className="tp-muted"> · {photoLabel(s.photo_indexes)}</span>}
                    </div>
                    {s.maps_url && (
                      <a className="tp-link" href={s.maps_url} target="_blank" rel="noopener noreferrer">Open in Maps</a>
                    )}
                  </div>
                </div>
                {lunchAfter(d, s) && (
                  <div className="tp-lunch">
                    <span className="tp-lunch-ico" aria-hidden="true">🍽</span>
                    <div className="tp-stop-body">
                      <div className="tp-stop-name" title={d.lunch.name}>Lunch: {d.lunch.name}</div>
                      <div className="tp-stop-time">
                        {d.lunch.arrive}
                        {d.lunch.minutes != null && <span className="tp-muted"> · {formatMinutes(d.lunch.minutes)}</span>}
                        {d.lunch.price_label && <span className="tp-muted"> · {d.lunch.price_label}</span>}
                        {d.lunch.rating != null && <span className="tp-muted"> · ★ {d.lunch.rating}</span>}
                      </div>
                      {d.lunch.maps_url && (
                        <a className="tp-link" href={d.lunch.maps_url} target="_blank" rel="noopener noreferrer">Open in Maps</a>
                      )}
                    </div>
                  </div>
                )}
              </li>
            ))}
            {d.end_time && <li className="tp-end">🏁 Finish around {d.end_time}</li>}
          </ol>
        </section>
      ))}

      {plan.traffic_windows.length > 0 && (
        <section className="tp-section" aria-label="Traffic">
          <div className="tp-chips">
            {plan.traffic_windows.map((w, i) => (
              <span key={i} className={`tp-chip tp-level-${w.level}`} title={[w.label, w.note].filter(Boolean).join(" — ")}>
                {trafficChipText(w)}
              </span>
            ))}
          </div>
          <p className="tp-note">Modelled from Google Maps traffic estimates, not official busy hours.</p>
        </section>
      )}

      <section className="tp-cost" aria-label="Cost estimate">
        <div className="tp-cost-top">
          <strong>{formatMoney(c.total, c.currency)}</strong>
          <span className="tp-muted"> total · {formatMoney(c.per_person, c.currency)} per person (estimate)</span>
        </div>
        <div className="tp-muted tp-cost-split">
          Travel {formatMoney(c.travel, c.currency)} · Food {formatMoney(c.food, c.currency)} ·{" "}
          {c.entry != null ? `Entry ${formatMoney(c.entry, c.currency)}` : "Entry fees not included"}
        </div>
        {c.assumptions.length > 0 && (
          <>
            <button type="button" className="pc-toggle" aria-expanded={showAssumptions}
                    onClick={() => setShowAssumptions((v) => !v)}>
              {showAssumptions ? "▾" : "▸"} Assumptions ({c.assumptions.length})
            </button>
            {showAssumptions && <ul className="tp-assume">{c.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>}
          </>
        )}
      </section>

      {plan.mode_options.length > 0 && (
        <section className="tp-section">
          <button type="button" className="pc-toggle" aria-expanded={showModes} onClick={() => setShowModes((v) => !v)}>
            {showModes ? "▾" : "▸"} Other ways to travel ({plan.mode_options.length})
          </button>
          {showModes && (
            <ul className="tp-modes">
              {plan.mode_options.map((m) => (
                <li key={m.mode}>
                  <span>{MODE_ICON[m.mode]} {MODE_LABEL[m.mode]}</span>
                  <span className="tp-muted">{modeOptionText(m)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {plan.tips.length > 0 && <ul className="tp-tips">{plan.tips.map((t, i) => <li key={i}>💡 {t}</li>)}</ul>}

      <footer className="pc-foot">{plan.attribution} · Estimates only</footer>
    </article>
  );
}
