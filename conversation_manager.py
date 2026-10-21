from datetime import datetime
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class ConversationState:
    def __init__(self, chat_id: int, user_id: int, user_name: str = ""):
        self.chat_id = chat_id
        self.user_id = user_id
        self.user_name = user_name
        self.status = "ACTIVE"  # ACTIVE, DEAL_CLOSED, ENDED, ESCALATED
        self.messages: List[dict] = []
        self.deal_details: dict = {
            "event_type": None,
            "date": None,
            "guest_count": None,
            "price": None,
            "notes": ""
        }
        self.is_deal_ready: bool = False
        self.phone_shared: bool = False
        self.created_at = datetime.now()
        self.last_activity = datetime.now()

    @property
    def turn_count(self) -> int:
        return sum(1 for m in self.messages if m.get("role") == "user")

    def add_message(self, role: str, text: str):
        self.messages.append({
            "role": role,
            "text": text,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })
        self.last_activity = datetime.now()

    def update_deal(self, new_info: dict):
        for k, v in new_info.items():
            if v and v != "UNKNOWN" and v != "None":
                self.deal_details[k] = v

        # סנכרון שדות לפורמט אחיד
        if "timeline" in self.deal_details and not self.deal_details.get("date"):
            self.deal_details["date"] = self.deal_details["timeline"]
        if "stated_budget" in self.deal_details and not self.deal_details.get("price"):
            self.deal_details["price"] = self.deal_details["stated_budget"]

    def format_history_for_prompt(self, max_turns: int = 10) -> str:
        recent = self.messages[-max_turns*2:] if len(self.messages) > max_turns*2 else self.messages
        if not recent:
            return "אין היסטוריית שיחה קודמת (זו ההודעה הראשונה)."

        lines = []
        for m in recent:
            role_title = "הלקוח" if m["role"] == "user" else "הסוכן (אנחנו)"
            lines.append(f"{role_title}: {m['text']}")
        return "\n".join(lines)


class ConversationManager:
    def __init__(self):
        # key: chat_id (or user_id) -> ConversationState
        self.active_conversations: Dict[int, ConversationState] = {}
        self.archived_conversations: List[ConversationState] = []

    def get_conversation(self, chat_id: int) -> Optional[ConversationState]:
        return self.active_conversations.get(chat_id)

    def get_or_create(self, chat_id: int, user_id: int, user_name: str = "") -> ConversationState:
        conv = self.active_conversations.get(chat_id)
        if not conv or conv.status in ["ENDED", "DEAL_CLOSED"]:
            conv = ConversationState(chat_id, user_id, user_name)
            self.active_conversations[chat_id] = conv
        return conv

    def end_conversation(self, chat_id: int, reason: str = "ENDED") -> Optional[ConversationState]:
        conv = self.active_conversations.get(chat_id)
        if conv:
            conv.status = reason
            self.archived_conversations.append(conv)
            del self.active_conversations[chat_id]
            logger.info(f"Conversation {chat_id} ended with reason: {reason}")
            return conv
        return None

    def get_deal_summary(self, conv: ConversationState) -> str:
        d = conv.deal_details
        return (
            f"📌 סוג אירוע: {d.get('event_type') or 'טרם סוכם'}\n"
            f"📅 תאריך: {d.get('date') or 'טרם סוכם'}\n"
            f"👥 כמות מוזמנים: {d.get('guest_count') or 'טרם סוכם'}\n"
            f"💰 מחיר/תקציב: {d.get('price') or 'טרם סוכם'}"
        )

conversation_manager = ConversationManager()
