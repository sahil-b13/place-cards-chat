import { CometChat } from "@cometchat/chat-sdk-javascript";
import { CometChatUIKit } from "@cometchat/chat-uikit-react";
import { messagePayload } from "./cards";
import { PLACE_CARDS_TYPE, formatTextCards } from "./cardView";
import { TRIP_PLAN_TYPE, formatTextPlan } from "./tripView";
import { messagePayload as tripPayload } from "./trip";
import { FALLBACK_TEXT_CARDS } from "../cometchat/config";

export { PLACE_CARDS_TYPE };

// Sends photos as normal media messages (in order), then ONE `place_cards` custom message (only if
// there are cards), then ONE `trip_plan` custom message (only if there are plans). `progress` is
// mutated so a retry after a failure resumes without re-sending what already went out:
// { photos: number, cards: boolean, plan: boolean }.
export async function sendPhotosAndCards({ receiverId, receiverType, files, cards, plans = [], progress, onStep }) {
  const type = receiverType === "group" ? CometChat.RECEIVER_TYPE.GROUP : CometChat.RECEIVER_TYPE.USER;
  for (let i = progress.photos; i < files.length; i++) {
    onStep?.(`Sending photo ${i + 1} of ${files.length}…`);
    const media = new CometChat.MediaMessage(receiverId, files[i], CometChat.MESSAGE_TYPE.IMAGE, type);
    await CometChatUIKit.sendMediaMessage(media);
    progress.photos = i + 1;
  }
  if (cards.length && !progress.cards) {
    onStep?.("Sending place cards…");
    if (FALLBACK_TEXT_CARDS) {
      // FALLBACK_TEXT_CARDS: plain formatted text, renders everywhere with no plugin
      await CometChatUIKit.sendTextMessage(new CometChat.TextMessage(receiverId, formatTextCards(cards), type));
    } else {
      // CustomMessage(receiverId, receiverType, customType, customData)
      const custom = new CometChat.CustomMessage(receiverId, type, PLACE_CARDS_TYPE, messagePayload(cards));
      custom.setMetadata?.({ incrementUnreadCount: true });
      await CometChatUIKit.sendCustomMessage(custom);
    }
    progress.cards = true;
  }
  if (plans.length && !progress.plan) {
    onStep?.("Sending travel plan…");
    if (FALLBACK_TEXT_CARDS) {
      await CometChatUIKit.sendTextMessage(new CometChat.TextMessage(receiverId, formatTextPlan(plans), type));
    } else {
      const custom = new CometChat.CustomMessage(receiverId, type, TRIP_PLAN_TYPE, tripPayload(plans));
      custom.setMetadata?.({ incrementUnreadCount: true });
      await CometChatUIKit.sendCustomMessage(custom);
    }
    progress.plan = true;
  }
}
