import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { readGps } from "../lib/exif";
import { resizeToJpeg } from "../lib/image";
import { analyzePhotos, planTrip } from "../lib/api";
import { initGroups, cardsToSend, needsDecision } from "../lib/cards";
import { sendPhotosAndCards } from "../lib/send";
import { DEFAULT_TRIP_OPTIONS, validateTripOptions, buildTripRequest, preparePlansForSend } from "../lib/trip";
import ReviewStep from "./ReviewStep.jsx";
import TripPlanBubble from "./TripPlanBubble.jsx";

const MAX_PHOTOS = 10;
const localIsoDate = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// Composer button + modal flow: pick -> analyzing -> review -> (planning -> plan preview) -> sending
export default function PlaceInfoToggle({ user, group }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="place-btn" title="Add place info to photos" onClick={() => setOpen(true)}>
        📍 Place info
      </button>
      {open && createPortal(<Flow user={user} group={group} onClose={() => setOpen(false)} />, document.body)}
    </>
  );
}

function Flow({ user, group, onClose }) {
  const receiverId = user ? user.getUid() : group.getGuid();
  const receiverType = user ? "user" : "group";
  const receiverName = user ? user.getName() : group.getName();

  const [step, setStep] = useState("pick"); // pick | analyzing | review | planning | plan | sending
  const [photos, setPhotos] = useState([]); // [{ file (resized), url, gps }]
  const [preparing, setPreparing] = useState(false);
  const [hint, setHint] = useState("");
  const [groups, setGroups] = useState([]);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [tripOn, setTripOn] = useState(false);
  const [tripOptions, setTripOptions] = useState(DEFAULT_TRIP_OPTIONS);
  const [planResult, setPlanResult] = useState(null); // { plans, status, warnings } from /api/trip-plan
  const progress = useRef({ photos: 0, cards: false, plan: false });
  const photosRef = useRef(photos);
  useEffect(() => {
    photosRef.current = photos;
  }, [photos]);

  useEffect(() => () => photosRef.current.forEach((p) => URL.revokeObjectURL(p.url)), []);

  async function addFiles(fileList) {
    setError("");
    const incoming = [...fileList].filter((f) => f.type.startsWith("image/"));
    const room = MAX_PHOTOS - photos.length;
    if (incoming.length > room) setError(`You can add up to ${MAX_PHOTOS} photos.`);
    setPreparing(true);
    const added = [];
    for (const original of incoming.slice(0, Math.max(room, 0))) {
      try {
        const gps = await readGps(original); // must read BEFORE resizing (resize strips EXIF)
        const file = await resizeToJpeg(original);
        added.push({ file, url: URL.createObjectURL(file), gps });
      } catch (e) {
        setError(`Skipped "${original.name}": ${e.message}`);
      }
    }
    setPhotos((p) => [...p, ...added]);
    setPreparing(false);
  }

  function removePhoto(i) {
    setPhotos((p) => {
      URL.revokeObjectURL(p[i].url);
      return p.filter((_, idx) => idx !== i);
    });
  }

  async function findPlaces() {
    setError("");
    setStep("analyzing");
    try {
      const results = await analyzePhotos(photos, hint);
      setGroups(initGroups(results));
      setStep("review");
    } catch (e) {
      setError(e.message);
      setStep("pick");
    }
  }

  async function send(cards, plans = []) {
    setError("");
    setStep("sending");
    try {
      await sendPhotosAndCards({
        receiverId,
        receiverType,
        files: photos.map((p) => p.file),
        cards,
        plans,
        progress: progress.current,
        onStep: setStatus,
      });
      onClose();
    } catch (e) {
      setError(`Sending failed (${progress.current.photos} of ${photos.length} photos went out): ${e.message || e.code}`);
      setStep(plans.length ? "plan" : groups.length ? "review" : "pick");
    }
  }

  // Confirmed cards (deduped) drive both the place_cards message and the plan request.
  const cards = cardsToSend(groups);
  const todayIso = localIsoDate();
  const tripErrors = validateTripOptions(tripOptions, todayIso);

  async function makePlan() {
    setError("");
    setStep("planning");
    try {
      const result = await planTrip(buildTripRequest(tripOptions, cards));
      setPlanResult(result);
      setStep("plan");
    } catch (e) {
      setError(e.message);
      setStep("review");
    }
  }

  // Plans as they will be sent (whitelisted + size-limited).
  const prepared = planResult?.plans?.length ? preparePlansForSend(planResult.plans) : null;

  const busy = step === "analyzing" || step === "sending" || step === "planning";
  const gpsCount = photos.filter((p) => p.gps).length;

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="modal" role="dialog" aria-label="Place info">
        <div className="modal-head">
          <h2>📍 Place info → {receiverName}</h2>
          <button className="link" disabled={busy} onClick={onClose}>Close</button>
        </div>

        {step === "pick" && (
          <div className="modal-body">
            <p className="muted small">
              Optional. We look up the place in each photo, you confirm it, then the photos and a compact
              place card are sent together. Your photo's GPS is only used for the lookup and is never sent in the chat.
            </p>
            <label className="file-pick">
              <input type="file" accept="image/*" multiple disabled={preparing || photos.length >= MAX_PHOTOS}
                     onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
              {preparing ? "Preparing photos…" : `Choose photos (${photos.length}/${MAX_PHOTOS})`}
            </label>
            {photos.length > 0 && (
              <div className="thumbs">
                {photos.map((p, i) => (
                  <div className="thumb" key={p.url}>
                    <img src={p.url} alt={`Photo ${i + 1}`} />
                    {p.gps && <span className="gps-badge" title="GPS found in this photo">GPS</span>}
                    <button type="button" aria-label={`Remove photo ${i + 1}`} onClick={() => removePhoto(i)}>×</button>
                  </div>
                ))}
              </div>
            )}
            {photos.length > 0 && (
              <p className="muted small">{gpsCount} of {photos.length} photos have location data.</p>
            )}
            <input className="text-input" placeholder="City or area hint (optional), e.g. Colaba, Mumbai"
                   value={hint} onChange={(e) => setHint(e.target.value)} maxLength={120} />
            {error && <p className="error">{error}</p>}
            <div className="modal-actions">
              <button className="secondary" disabled={!photos.length || preparing} onClick={() => send([])}>
                Send photos without place info
              </button>
              <button className="primary" disabled={!photos.length || preparing} onClick={findPlaces}>
                Find place info
              </button>
            </div>
          </div>
        )}

        {step === "analyzing" && (
          <div className="modal-body center">
            <div className="spinner" />
            <p>Looking up places in {photos.length} photo{photos.length > 1 ? "s" : ""}…</p>
          </div>
        )}

        {step === "sending" && (
          <div className="modal-body center">
            <div className="spinner" />
            <p>{status || "Sending…"}</p>
          </div>
        )}

        {step === "review" && (
          <ReviewStep
            groups={groups}
            setGroups={setGroups}
            photos={photos}
            hint={hint}
            error={error}
            blocked={needsDecision(groups)}
            onBack={() => { setError(""); setStep("pick"); }}
            onSendPlain={() => send([])}
            onSend={() => send(cards)}
            trip={{
              on: tripOn,
              setOn: setTripOn,
              options: tripOptions,
              setOptions: setTripOptions,
              errors: tripErrors,
              cards,
              todayIso,
              onPlan: makePlan,
            }}
          />
        )}

        {step === "planning" && (
          <div className="modal-body center">
            <div className="spinner" />
            <p>Planning the day with live travel times…</p>
          </div>
        )}

        {step === "plan" && planResult && (
          <div className="modal-body">
            {planResult.status === "unsupported" || !prepared ? (
              <p className="notice">
                {planResult.warnings?.[0] ||
                  "These places are too far apart for a one-day plan (different cities or more than ~100 km)."}{" "}
                You can go back and change the places, or send without a travel plan.
              </p>
            ) : (
              <>
                {planResult.status === "partial" && planResult.warnings?.length > 0 && (
                  <ul className="tp-warnings">{planResult.warnings.slice(0, 5).map((w, i) => <li key={i}>⚠ {w}</li>)}</ul>
                )}
                <p className="muted small">Preview — this is what {receiverName} will see.</p>
                <div className="tp-preview"><TripPlanBubble customData={{ plans: prepared.plans }} /></div>
                {!prepared.fits && (
                  <p className="muted small">This plan is large; some detail may be trimmed by the chat service.</p>
                )}
              </>
            )}
            {error && <p className="error">{error}</p>}
            <div className="modal-actions">
              <button className="link" onClick={() => { setError(""); setStep("review"); }}>← Edit plan options</button>
              <button className="secondary" onClick={() => send(cards)}>
                {cards.length ? `Send photos + ${cards.length} card${cards.length > 1 ? "s" : ""} (no plan)` : "Send photos"}
              </button>
              {prepared && planResult.status !== "unsupported" && (
                <button className="primary" onClick={() => send(cards, prepared.plans)}>Send photos, cards + travel plan</button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
