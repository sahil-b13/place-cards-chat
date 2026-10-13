import { useEffect, useState } from "react";
import { CometChatUIKit } from "@cometchat/chat-uikit-react";
import { DEMO_USERS, missingConfig } from "./cometchat/config";
import { initCometChat, loginAs, logout, readableError } from "./cometchat/session";
import Chat from "./components/Chat.jsx";

export default function App() {
  const missing = missingConfig();
  const [phase, setPhase] = useState(missing.length ? "config" : "booting"); // config | booting | login | ready
  const [busyUid, setBusyUid] = useState(null);
  const [error, setError] = useState("");

  // Resume an existing per-tab session (page refresh) if there is one.
  useEffect(() => {
    if (missing.length) return;
    initCometChat()
      .then(() => setPhase(CometChatUIKit.getLoggedInUser() ? "ready" : "login"))
      .catch((e) => {
        setError(readableError(e));
        setPhase("login");
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleLogin(uid) {
    setError("");
    setBusyUid(uid);
    try {
      await loginAs(uid);
      setPhase("ready");
    } catch (e) {
      setError(readableError(e));
    } finally {
      setBusyUid(null);
    }
  }

  async function handleLogout() {
    try {
      await logout();
    } finally {
      setPhase("login");
    }
  }

  if (phase === "config") {
    return (
      <div className="center-screen">
        <div className="card">
          <h1>Setup needed</h1>
          <p>Create <code>frontend/.env</code> from <code>.env.example</code> and set:</p>
          <ul>{missing.map((m) => <li key={m}><code>{m}</code></li>)}</ul>
          <p className="muted">Then restart <code>npm run dev</code>.</p>
        </div>
      </div>
    );
  }

  if (phase === "booting") {
    return <div className="center-screen"><p className="muted">Connecting to CometChat…</p></div>;
  }

  if (phase === "login") {
    return (
      <div className="center-screen">
        <div className="card">
          <h1>📍 Place Cards</h1>
          <p className="muted">Dev login — pick a test user. Open a second tab and pick the other one.</p>
          <div className="user-buttons">
            {DEMO_USERS.map((u) => (
              <button key={u.uid} disabled={!!busyUid} onClick={() => handleLogin(u.uid)}>
                {busyUid === u.uid ? "Signing in…" : `Continue as ${u.uid}`}
              </button>
            ))}
          </div>
          {error && <p className="error">{error}</p>}
          <p className="fineprint">Auth Key login is for demos only; production should use server-minted auth tokens.</p>
        </div>
      </div>
    );
  }

  return <Chat onLogout={handleLogout} />;
}
