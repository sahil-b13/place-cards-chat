import { useState } from "react";
import { readCards, photoLabel, stars, formatCount, formatDistance } from "../lib/cardView";

// Renders the customData of a `place_cards` message: horizontally scrollable compact cards.
// Same bubble for sender and receiver. All text is rendered as React text (never as HTML).
export default function PlaceCardsBubble({ customData }) {
  const cards = readCards(customData);
  if (!cards.length) {
    return <div className="pc-bubble pc-empty">📍 Place info is unavailable for this message.</div>;
  }
  return (
    <div className="pc-bubble">
      <div className="pc-scroller" role="list" aria-label="Place cards" tabIndex={0}>
        {cards.map((c, i) => (
          <PlaceCard key={`${c.place_id || c.name}-${i}`} card={c} />
        ))}
      </div>
      {cards.length > 1 && <div className="pc-hint">{cards.length} places · swipe for more →</div>}
    </div>
  );
}

function PlaceCard({ card: c }) {
  const [showReviews, setShowReviews] = useState(false);
  const [showNearby, setShowNearby] = useState(false);
  const label = photoLabel(c.photo_indexes);

  return (
    <article className="pc-card" role="listitem">
      {label && <div className="pc-photos">{label}</div>}

      <header className="pc-head">
        <h3 className="pc-name" title={c.name}>{c.name}</h3>
        <span className={`pc-chip pc-cat-${c.category}`}>{c.category}</span>
      </header>

      <div className="pc-meta">
        {c.rating != null && (
          <span className="pc-rating" aria-label={`Rated ${c.rating} out of 5`}>
            <span className="pc-stars" aria-hidden="true">{stars(c.rating)}</span> {c.rating}
            {c.rating_count != null && <span className="pc-muted"> ({formatCount(c.rating_count)})</span>}
          </span>
        )}
        {c.price_label && <span className="pc-price">{c.price_label}</span>}
      </div>

      {(c.open_now != null || c.hours_today) && (
        <div className="pc-open">
          {c.open_now != null && (
            <span className={`pc-badge ${c.open_now ? "pc-open-yes" : "pc-open-no"}`}>
              {c.open_now ? "Open now" : "Closed"}
            </span>
          )}
          {c.hours_today && <span className="pc-muted">{c.hours_today}</span>}
        </div>
      )}

      {c.summary && <p className="pc-summary">{c.summary}</p>}
      {(c.address || c.area) && <p className="pc-address">{c.address || c.area}</p>}

      {c.reviews.length > 0 && (
        <section className="pc-section">
          <button type="button" className="pc-toggle" aria-expanded={showReviews}
                  onClick={() => setShowReviews((v) => !v)}>
            {showReviews ? "▾" : "▸"} Reviews ({c.reviews.length})
          </button>
          {showReviews && (
            <ul className="pc-list">
              {c.reviews.map((r, i) => (
                <li key={i}>
                  <div className="pc-review-top">
                    <strong>{r.author}</strong>
                    {r.rating != null && <span className="pc-stars" aria-label={`${r.rating} stars`}>{stars(r.rating)}</span>}
                    {r.when && <span className="pc-muted">{r.when}</span>}
                  </div>
                  <p className="pc-review-text">“{r.text}”</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {!c.is_restaurant && c.nearby.length > 0 && (
        <section className="pc-section">
          <button type="button" className="pc-toggle" aria-expanded={showNearby}
                  onClick={() => setShowNearby((v) => !v)}>
            {showNearby ? "▾" : "▸"} Nearby restaurants ({c.nearby.length})
          </button>
          {showNearby && (
            <ul className="pc-list">
              {c.nearby.map((n, i) => (
                <li key={i} className="pc-nearby">
                  <span className="pc-nearby-name">{n.name}</span>
                  <span className="pc-muted">
                    {n.rating != null && `★ ${n.rating}`}
                    {n.rating != null && n.distance_m != null && " · "}
                    {formatDistance(n.distance_m)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <div className="pc-actions">
        {c.maps_url && (
          <a className="pc-btn pc-btn-primary" href={c.maps_url} target="_blank" rel="noopener noreferrer">
            Open in Maps
          </a>
        )}
        {c.website && (
          <a className="pc-btn" href={c.website} target="_blank" rel="noopener noreferrer">
            {c.is_restaurant ? "Website / menu" : "Website"}
          </a>
        )}
      </div>

      <footer className="pc-foot">
        <span>{c.attribution}</span>
        {c.source === "user" && <span> · picked by sender</span>}
      </footer>
    </article>
  );
}
