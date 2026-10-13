import PlaceCardsBubble from "../components/PlaceCardsBubble.jsx";
import { previewText, PLACE_CARDS_TYPE } from "../lib/cardView";

// UI Kit v7 message plugin (replaces v6 CometChatMessageTemplate). Registered via
// <CometChatProvider plugins={[PlaceCardsPlugin]}> and prepended before the built-in plugins.
// A CometChat.CustomMessage has category "custom"; our type is "place_cards".
export const PlaceCardsPlugin = {
  id: "place-cards",
  messageTypes: [PLACE_CARDS_TYPE],
  messageCategories: ["custom"],

  renderBubble(message) {
    return <PlaceCardsBubble customData={message.getCustomData?.()} />;
  },

  // Sender can delete their own card message; nothing else (no edit/reply-with-text semantics).
  getOptions(message, context) {
    return [
      {
        id: "delete",
        title: context.getLocalizedString?.("delete") ?? "Delete",
        senderOnly: true,
        onClick: (msg) => context.onDeleteMessage?.(msg),
      },
    ];
  },

  getLastMessagePreview(message) {
    return previewText(message.getCustomData?.());
  },
};
