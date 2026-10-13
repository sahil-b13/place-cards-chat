import { useEffect, useState } from "react";
import {
  CometChatProvider,
  CometChatConversations,
  CometChatUsers,
  CometChatMessageHeader,
  CometChatMessageList,
  CometChatMessageComposer,
  CometChatUIKit,
} from "@cometchat/chat-uikit-react";
import PlaceInfoToggle from "./PlaceInfoToggle.jsx";
import { PlaceCardsPlugin } from "../plugins/PlaceCardsPlugin.jsx";
import { TripPlanPlugin } from "../plugins/TripPlanPlugin.jsx";

// Module-level so the array identity is stable across renders.
const PLUGINS = [PlaceCardsPlugin, TripPlanPlugin];

function useIsMobile(breakpoint = 768) {
  const query = `(max-width: ${breakpoint}px)`;
  const [isMobile, setIsMobile] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const onChange = () => setIsMobile(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [query]);
  return isMobile;
}

export default function Chat({ onLogout }) {
  const me = CometChatUIKit.getLoggedInUser();
  const isMobile = useIsMobile();
  const [tab, setTab] = useState("chats"); // chats | users
  const [chatUser, setChatUser] = useState();
  const [chatGroup, setChatGroup] = useState();
  const hasSelection = Boolean(chatUser || chatGroup);

  function openUser(user) {
    setChatUser(user);
    setChatGroup(undefined);
  }

  function handleConversationClick(conversation) {
    const entity = conversation.getConversationWith();
    if (conversation.getConversationType() === "user") {
      setChatUser(entity);
      setChatGroup(undefined);
    } else {
      setChatGroup(entity);
      setChatUser(undefined);
    }
  }

  function clearSelection() {
    setChatUser(undefined);
    setChatGroup(undefined);
  }

  const sidebar = (
    <div className="sidebar">
      <div className="sidebar-top">
        <span>Signed in as <strong>{me?.getUid()}</strong></span>
        <button className="link" onClick={onLogout}>Log out</button>
      </div>
      <div className="tabs">
        <button className={tab === "chats" ? "active" : ""} onClick={() => setTab("chats")}>Chats</button>
        <button className={tab === "users" ? "active" : ""} onClick={() => setTab("users")}>Start new chat</button>
      </div>
      <div className="sidebar-list">
        {tab === "chats" ? (
          <CometChatConversations onItemClick={handleConversationClick} />
        ) : (
          <CometChatUsers
            onItemClick={(user) => {
              openUser(user);
              setTab("chats");
            }}
          />
        )}
      </div>
    </div>
  );

  const messagePane = hasSelection ? (
    <div className="message-pane">
      <CometChatMessageHeader user={chatUser} group={chatGroup} onBack={clearSelection} />
      <CometChatMessageList user={chatUser} group={chatGroup} />
      <CometChatMessageComposer
        user={chatUser}
        group={chatGroup}
        auxiliaryButtonView={<PlaceInfoToggle key={chatUser?.getUid() || chatGroup?.getGuid()} user={chatUser} group={chatGroup} />}
      />
    </div>
  ) : (
    <div className="message-pane empty">
      <p className="muted">Select a conversation, or pick “Start new chat”.</p>
    </div>
  );

  return (
    <CometChatProvider plugins={PLUGINS}>
      <div className="app-shell">
        {isMobile ? (hasSelection ? messagePane : sidebar) : (<>{sidebar}{messagePane}</>)}
      </div>
    </CometChatProvider>
  );
}
