// Form for the travel plan: start time, start place (typed text only), travelers, objective,
// plan type, optional date and optional per-person entry fee for each confirmed place.
export default function TripPlanOptions({ options, onChange, places, errors, todayIso }) {
  const set = (patch) => onChange({ ...options, ...patch });
  const setFee = (id, value) => set({ entry_fees: { ...options.entry_fees, [id]: value } });

  return (
    <div className="tp-options">
      <div className="tp-grid">
        <label className="tp-field">
          <span>Start time</span>
          <input type="time" className="text-input" value={options.start_time}
                 onChange={(e) => set({ start_time: e.target.value })} />
        </label>
        <label className="tp-field">
          <span>Travelers</span>
          <input type="number" className="text-input" min={1} max={20} step={1} value={options.travelers}
                 onChange={(e) => set({ travelers: e.target.value })} />
        </label>
        <label className="tp-field tp-wide">
          <span>Start place (type it, optional)</span>
          <input type="text" className="text-input" maxLength={120} placeholder="e.g. Colaba, Mumbai"
                 value={options.start_text} onChange={(e) => set({ start_text: e.target.value })} />
        </label>
        <label className="tp-field">
          <span>Date (optional)</span>
          <input type="date" className="text-input" min={todayIso} value={options.date}
                 onChange={(e) => set({ date: e.target.value })} />
        </label>
        <label className="tp-field">
          <span>Best order by</span>
          <select className="text-input" value={options.objective} onChange={(e) => set({ objective: e.target.value })}>
            <option value="least_time">Least time</option>
            <option value="least_distance">Least distance</option>
          </select>
        </label>
        <label className="tp-field tp-wide">
          <span>Plan type</span>
          <select className="text-input" value={options.plan} onChange={(e) => set({ plan: e.target.value })}>
            <option value="both">Both: cheapest + comfort</option>
            <option value="cheapest">Cheapest</option>
            <option value="comfort">Comfort</option>
          </select>
        </label>
      </div>

      {places.length > 0 && (
        <details className="tp-fees">
          <summary>Entry fees per person (optional)</summary>
          <div className="tp-fee-list">
            {places.map((c) => (
              <label key={c.place_id} className="tp-fee">
                <span title={c.name}>{c.name}</span>
                <input type="number" className="text-input" min={0} step="any" inputMode="decimal" placeholder="0"
                       value={options.entry_fees[c.place_id] ?? ""} onChange={(e) => setFee(c.place_id, e.target.value)} />
              </label>
            ))}
          </div>
          <p className="muted small">Left empty, entry fees are shown as “not included”.</p>
        </details>
      )}

      <p className="muted small">
        Your location is never read: the start place is only the text you type. Times, distances and traffic come from
        Google Maps; costs are estimates from editable assumptions.
      </p>
      {errors.length > 0 && <ul className="error tp-errors">{errors.map((e) => <li key={e}>{e}</li>)}</ul>}
    </div>
  );
}
