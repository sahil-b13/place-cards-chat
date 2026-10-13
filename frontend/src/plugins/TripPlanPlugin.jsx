import TripPlanBubble from "../components/TripPlanBubble.jsx";
import { previewText, TRIP_PLAN_TYPE } from "../lib/tripView";

// UI Kit v7 message plugin for `trip_plan` custom messages (same pattern as PlaceCardsPlugin).
export const TripPlanPlugin = {
  id: "trip-plan",
  messageTypes: [TRIP_PLAN_TYPE],
  messageCategories: ["custom"],

  renderBubble(message) {
    return <TripPlanBubble customData={message.getCustomData?.()} />;
  },

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
