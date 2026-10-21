import re
import time
from collections import defaultdict
from typing import Dict, List, Tuple
import config

class SpamFilter:
    def __init__(self):
        # user_id -> list of timestamps
        self.user_message_timestamps: Dict[int, List[float]] = defaultdict(list)
        # user_id -> list of recent message texts
        self.user_recent_messages: Dict[int, List[str]] = defaultdict(list)

        # מילות מפתח שמעידות על כוונת אירוע לגיטימית
        self.event_intent_keywords = [
            "אירוע", "אירועים", "חתונה", "חתונות", "כנס", "כנסים", "בר מצווה", "בת מצווה",
            "יום הולדת", "יומולדת", "מסיבה", "מסיבת", "ברית", "בריתה", "חינה", "להפיק",
            "הפקה", "לחגוג", "חגיגה", "אורחים", "מוזמנים", "משתתפים", "קייטרינג", "תאריך",
            "תקציב", "הצעת מחיר", "סגירת אירוע", "אולם", "גן אירועים", "וילה", "שטח"
        ]

        # ביטויים מסחריים / הצעות ספקים / חיפוש עבודה / פרסומות
        self.commercial_spam_patterns = [
            r"רוצה לקנות", r"רק אצלנו", r"דברים שווים", r"מבצע(?:ים)?", r"הנח(?:ה|ות)",
            r"קופונ(?:ים)?", r"מחירים ללא תחרות", r"משלוח(?:ים)?", r"סופרמרקט", r"רמי לוי",
            r"שופרסל", r"אושר עד", r"קטלוג", r"חנות אונליין", r"הלווא(?:ה|ות)", r"ביטקוין",
            r"קריפטו", r"פורקס", r"הכנסה פסיבית", r"קזינו", r"הימורים", r"מחפש(?:ת)? עבודה",
            r"קורות חיים", r"קו\"ח", r"דרושים", r"משר(?:ה|ות)", r"הצעת ספק", r"שיתוף פעולה עסקי",
            r"שירותי קידום", r"בניית אתרים", r"שיווק דיגיטלי", r"לידים חמים", r"שירותי seo"
        ]

    def has_event_intent(self, text: str) -> bool:
        lower = text.lower()
        return any(kw in lower for kw in self.event_intent_keywords)

    def is_commercial_spam(self, text: str) -> bool:
        lower = text.lower()
        for pattern in self.commercial_spam_patterns:
            if re.search(pattern, lower):
                return True
        return False

    def is_spam(self, user_id: int, text: str, current_turn_count: int = 0) -> Tuple[bool, str]:
        """
        בודק האם ההודעה היא ספאם או מפרה הגבלות, ללא הפעלת LLM.
        מחזיר (is_spam, message_to_user).
        אם is_spam הוא False, message_to_user הוא ריק.
        """
        clean_text = text.strip()
        now = time.time()

        # 1. בדיקת אורך מינימלי
        if len(clean_text) < config.MIN_MESSAGE_LENGTH:
            return True, "ההודעה קצרה מדי. אנא שלח פרטים לגבי האירוע שברצונך להפיק."

        # 2. בדיקת אורך מקסימלי חריג (מניעת הצפת טקסט ענקי)
        if len(clean_text) > 1500:
            return True, "ההודעה ארוכה מדי. אנא תמצת את פנייתך בכמה משפטים עיקריים."

        # 3. מילים מפורשות של ספאם או בדיקות ספאם
        lower_text = clean_text.lower()
        if lower_text in ["ספאם", "spam", "זה ספאם", "this is spam"]:
            return True, "זוהתה הודעת בדיקה / ספאם."

        # 4. בדיקת קישורים חשודים
        if re.search(r'(https?://\S+|t\.me/\S+)', clean_text):
            return True, "שליחת קישורים אינה מותרת בצ'אט הראשוני."

        # 5. בדיקת תווים חוזרים (ג'יבריש כגון 'חחחחחח', 'ssssss' או '111111')
        if re.search(r'(.)\1{5,}', clean_text):
            return True, "ההודעה כוללת רצף תווים חוזר ואינה ברורה."

        # 6. בדיקת מילים חוזרות ברצף
        if re.search(r'\b(\w+)\b(?:\s+\1\b){2,}', clean_text, re.IGNORECASE):
            return True, "ההודעה כוללת חזרתיות רבה על אותה מילה."

        # 7. בדיקת ספאם שיווקי / הצעות ספקים / פרסומות ללא כוונת אירוע (NON_LEAD)
        if self.is_commercial_spam(clean_text) and not self.has_event_intent(clean_text):
            return True, "הודעה שיווקית / הצעת ספק ללא הקשר לאירוע (NON_LEAD)."

        # 8. בדיקת קצב הודעות (Rate Limiting)
        timestamps = self.user_message_timestamps[user_id]
        timestamps = [ts for ts in timestamps if now - ts <= config.SPAM_WINDOW_SECONDS]
        self.user_message_timestamps[user_id] = timestamps

        if len(timestamps) >= config.SPAM_MAX_MESSAGES_IN_WINDOW:
            return True, "⚠️ קצב ההודעות מהיר מדי. אנא המתן מספר שניות לפני שליחת ההודעה הבאה."

        self.user_message_timestamps[user_id].append(now)

        # 9. בדיקת הודעות כפולות/חוזרות ברצף
        recent = self.user_recent_messages[user_id]
        if recent and recent[-1].lower() == clean_text.lower():
            if recent.count(clean_text.lower()) >= config.MAX_REPEATED_MESSAGES:
                return True, "⚠️ הודעה זו נשלחה כבר מספר פעמים ברצף. אנו מעבדים את הפנייה שלך, אנא המתן."
        recent.append(clean_text.lower())
        if len(recent) > 5:
            self.user_recent_messages[user_id] = recent[-5:]

        # 10. בדיקת חריגה מכמות סבבי שיחה מקסימלית
        if current_turn_count >= config.MAX_CONVERSATION_TURNS:
            return True, f"הגענו למגבלת ההודעות בשיחה האוטומטית. לתיאום ישיר ניתן ליצור קשר טלפוני ב-{config.COMPANY_PHONE}."

        return False, ""

    def reset_user(self, user_id: int):
        self.user_message_timestamps.pop(user_id, None)
        self.user_recent_messages.pop(user_id, None)

spam_filter = SpamFilter()
