// Central place for CometChat credentials (read from Vite env).
// NOTE: the Auth Key in client code is for dev/demo ONLY. In production mint
// auth tokens server-side and use CometChatUIKit.loginWithAuthToken().
export const COMETCHAT = {
  APP_ID: import.meta.env.VITE_COMETCHAT_APP_ID,
  REGION: import.meta.env.VITE_COMETCHAT_REGION,
  AUTH_KEY: import.meta.env.VITE_COMETCHAT_AUTH_KEY,
};

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export const DEMO_USERS = [
  { uid: "user1", name: "User One" },
  { uid: "user2", name: "User Two" },
];

export function missingConfig() {
  return Object.entries({
    VITE_COMETCHAT_APP_ID: COMETCHAT.APP_ID,
    VITE_COMETCHAT_AUTH_KEY: COMETCHAT.AUTH_KEY,
    VITE_COMETCHAT_REGION: COMETCHAT.REGION,
  })
    .filter(([, v]) => !v)
    .map(([k]) => k);
}

// Phase 4 fallback: send place info as ONE formatted text message instead of the custom
// `place_cards` message (use only if the custom bubble can't be made to work in your setup).
export const FALLBACK_TEXT_CARDS = import.meta.env.VITE_FALLBACK_TEXT_CARDS === "true";
