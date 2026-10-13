import { CometChat } from "@cometchat/chat-sdk-javascript";
import { CometChatUIKit, UIKitSettingsBuilder } from "@cometchat/chat-uikit-react";
import { COMETCHAT, DEMO_USERS } from "./config";

let initPromise = null;

// init() must resolve before login(); login() must resolve before rendering UI Kit components.
// StorageMode.SESSION keeps the login per browser TAB, so two tabs can be two different users
// (the default localStorage mode would share one session across tabs).
export function initCometChat() {
  if (!initPromise) {
    const settings = new UIKitSettingsBuilder()
      .setAppId(COMETCHAT.APP_ID)
      .setRegion(COMETCHAT.REGION)
      .setAuthKey(COMETCHAT.AUTH_KEY)
      .setStorageMode(CometChat.StorageMode.SESSION)
      .subscribePresenceForAllUsers()
      .build();
    initPromise = CometChatUIKit.init(settings).catch((e) => {
      initPromise = null; // allow retry
      throw e;
    });
  }
  return initPromise; // resolves to the existing session's user, or null
}

// Dev-only convenience: if the demo user doesn't exist yet, create it with the Auth Key.
async function ensureUser(uid) {
  const known = DEMO_USERS.find((u) => u.uid === uid);
  const user = new CometChat.User(uid);
  user.setName(known?.name ?? uid);
  await CometChatUIKit.createUser(user);
}

export async function loginAs(uid) {
  await initCometChat();
  const current = CometChatUIKit.getLoggedInUser();
  if (current && current.getUid() === uid) return current;
  if (current) await CometChatUIKit.logout();
  try {
    return await CometChatUIKit.login(uid);
  } catch (err) {
    if (err?.code === "ERR_UID_NOT_FOUND") {
      await ensureUser(uid);
      return CometChatUIKit.login(uid);
    }
    throw err;
  }
}

export async function logout() {
  await CometChatUIKit.logout();
}

export function readableError(err) {
  return err?.message || err?.code || String(err);
}
