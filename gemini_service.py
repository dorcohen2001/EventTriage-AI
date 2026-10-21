import html
import json
import logging
import re
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import openpyxl
from google import genai
from google.genai import types

import config
from schedule_manager import schedule_manager
from conversation_manager import ConversationState

logger = logging.getLogger(__name__)

class GeminiService:
    def __init__(self):
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self._all_historical_events: List[dict] = []
        self._load_all_events()

    def _read_policy(self) -> str:
        if config.POLICY_FILE.exists():
            try:
                return config.POLICY_FILE.read_text(encoding="utf-8")
            except Exception as e:
                logger.error(f"Error reading policy file: {e}")
        return "מדיניות: הפקות אירועים B2B ופרטיים, מחירים וזמני היערכות כמקובל."

    def _load_all_events(self):
        """
        טוען פעם אחת את כל אירועי העבר מ-Excel לזיכרון ה-Python לצורך סינון מקדים מהיר ב-0 טוקנים.
        """
        if not config.HISTORY_FILE.exists():
            return

        try:
            wb = openpyxl.load_workbook(config.HISTORY_FILE, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows or len(rows) < 2:
                return

            self._all_historical_events = []
            for r in rows[1:]:
                ev_id = str(r[0] or "")
                ev_type = str(r[1] or "")
                guests = int(r[2]) if isinstance(r[2], (int, float)) else 0
                budget = float(r[3]) if isinstance(r[3], (int, float)) else 0.0
                status = str(r[4] or "")
                cat = str(r[5] or "")
                msg_text = str(r[6] or "")
                action = str(r[7] or "")
                notes = str(r[8] if len(r) > 8 and r[8] else "")

                self._all_historical_events.append({
                    "event_id": ev_id,
                    "event_type": ev_type,
                    "guest_count": guests,
                    "actual_budget": budget,
                    "status_or_profitability": status,
                    "classified_category": cat,
                    "message_text": msg_text,
                    "suggested_action": action,
                    "historical_notes": notes
                })

            logger.info(f"Loaded {len(self._all_historical_events)} historical events for pre-filtering.")
        except Exception as e:
            logger.error(f"Error loading events from Excel: {e}")

    def _extract_intent_clues(self, text: str, conv: Optional[ConversationState]) -> Tuple[Optional[str], Optional[int], Optional[float]]:
        """
        מחלץ רמזים בקוד Python (סוג אירוע, כמות אורחים, תקציב) מהטקסט ומהיסטוריית השיחה (0 טוקנים).
        """
        combined = text.lower()
        if conv:
            for m in conv.messages:
                combined += " " + m.get("text", "").lower()

        # 1. זיהוי סוג אירוע
        detected_type = None
        if conv and conv.deal_details.get("event_type") and conv.deal_details["event_type"] != "Unknown":
            detected_type = conv.deal_details["event_type"]
        else:
            if any(w in combined for w in ["כנס", "כנסים", "עובדים", "חברה", "הייטק", "עסקי", "b2b", "האקתון", "השקה", "הנהלה", "גיבוש", "סוף שנה"]):
                detected_type = "Corporate"
            elif any(w in combined for w in ["חתונה", "חתונות", "חתונת", "בר מצווה", "בת מצווה", "ברית", "בריתה", "חינה", "שטח", "וילה", "שבת חתן", "מטע"]):
                detected_type = "Private"
            elif any(w in combined for w in ["גג", "יום הולדת", "יומולדת", "בוטיק", "קוקטייל", "ארוחת שף", "פרישה", "אינטימי", "רווקות"]):
                detected_type = "Boutique"

        # 2. זיהוי כמות אורחים
        detected_guests = None
        if conv and conv.deal_details.get("guest_count"):
            try:
                detected_guests = int(conv.deal_details["guest_count"])
            except:
                pass
        if detected_guests is None:
            match = re.search(r'(\d{2,4})\s*(?:איש|אנשים|מוזמנים|אורחים|עובדים|משתתפים)?', text)
            if match:
                detected_guests = int(match.group(1))

        # 3. זיהוי תקציב
        detected_budget = None
        if conv and conv.deal_details.get("price"):
            try:
                detected_budget = float(conv.deal_details["price"])
            except:
                pass
        if detected_budget is None:
            match_k = re.search(r'(\d+)\s*(?:אלף|k)', text, re.IGNORECASE)
            if match_k:
                detected_budget = float(match_k.group(1)) * 1000
            else:
                match_num = re.search(r'(\d{4,6})\s*(?:ש"ח|שח|שקל|₪)?', text)
                if match_num:
                    detected_budget = float(match_num.group(1))

        return detected_type, detected_guests, detected_budget

    def get_top_relevant_events(self, text: str, conv: Optional[ConversationState], top_k: int = 4) -> List[dict]:
        """
        מנגנון הסינון המקדים: מדרג את כל 106 האירועים בקוד Python ומחזיר רק את 3-4 הרלוונטיים ביותר!
        חוסך 95% מעלות הטוקנים בכל קריאה!
        """
        if not self._all_historical_events:
            self._load_all_events()

        if not self._all_historical_events:
            return []

        det_type, det_guests, det_budget = self._extract_intent_clues(text, conv)
        text_lower = text.lower()

        scored_events = []
        for ev in self._all_historical_events:
            score = 0.0

            # התאמת סוג אירוע (משקל גבוה)
            if det_type and ev["event_type"] == det_type:
                score += 50.0

            # קרבה בכמות מוזמנים
            if det_guests and ev["guest_count"] > 0:
                diff = abs(ev["guest_count"] - det_guests)
                score += max(0.0, 30.0 - (diff * 0.25))

            # קרבה בתקציב
            if det_budget and ev["actual_budget"] > 0:
                diff_b = abs(ev["actual_budget"] - det_budget)
                score += max(0.0, 20.0 - (diff_b / 5000.0))

            # חפיפת מילות מפתח ממרכיבי ההפקה
            for kw in ["במות", "הגברה", "מסכים", "שטח", "וילה", "שף", "חוף", "גנרטור", "יקב", "לייזר", "דיגיי", "בר"]:
                if kw in text_lower and (kw in ev["historical_notes"] or kw in ev["message_text"]):
                    score += 8.0

            scored_events.append((score, ev))

        # מיון לפי הציון הגבוה ביותר
        scored_events.sort(key=lambda x: x[0], reverse=True)

        # אם אין התאמות כלל (הודעה מעורפלת ראשונה), נותנים דוגמה מכל קטגוריה
        if scored_events[0][0] == 0:
            sample = []
            for target_cat in ["Corporate", "Private", "Boutique", "Corporate"]:
                for _, ev in scored_events:
                    if ev["event_type"] == target_cat and ev not in sample:
                        sample.append(ev)
                        break
            return sample[:top_k]

        return [ev for _, ev in scored_events[:top_k]]

    def format_filtered_history_table(self, events: List[dict]) -> str:
        """
        מפרמט רק את 3-4 האירועים הרלוונטיים לטבלת Markdown קומפקטית (פחות מ-150 טוקנים במקום 3,000!).
        """
        if not events:
            return "אין אירועי עבר רלוונטיים."

        lines = [
            "### אירועי עבר נבחרים הדומים ביותר לפנייה (מתוך מאגר החברה):",
            "| מזהה (ID) | סוג אירוע | כמות מוזמנים | תקציב בפועל | סטטוס ורווחיות | פרטי הפקה והערות |",
            "|---|---|---|---|---|---|"
        ]
        for ev in events:
            b_str = f"{int(ev['actual_budget']):,} ₪" if ev['actual_budget'] > 0 else "לא צוין"
            lines.append(f"| {ev['event_id']} | {ev['event_type']} | {ev['guest_count']} | {b_str} | {ev['status_or_profitability']} | {ev['historical_notes']} |")

        return "\n".join(lines)

    def build_system_instruction(self, relevant_events_table: str) -> str:
        policy_doc = self._read_policy()
        schedule_summary = schedule_manager.get_booked_dates_summary_for_prompt()

        return f"""אתה סוכן AI לסינון, הערכה עסקית, מציאת דמיון היסטורי וניתוב לידים בחברת הפקות אירועים (EventTriage AI).

### מקורות נתונים והנחיות עבודה:
1. עיין במסמך המדיניות העסקית הבא:
{policy_doc}

2. עיין במאגר אירועי העבר הרלוונטיים לפנייה הנוכחית:
{relevant_events_table}

3. עיין בלוח הזמנים של החברה (זמינות יומן ותאריכים תפוסים):
{schedule_summary}

---
### תפקידי הסוכן בכל פנייה:
1. **חילוץ ישויות:** זהה כמות מוזמנים, סוג אירוע, זמנים/תאריך ותקציב שהוגדר.
2. **הערכת היתכנות:** הצלב את הנתונים מול המדיניות (תקציבי מינימום וזמני היערכות).
3. **שכבת דמיון (Similarity Layer):**
   - מצא מתוך אירועי העבר לעיל את 1-2 האירועים בעלי הדמיון הגבוה ביותר לפנייה הנוכחית.
   - ציין את מזהה האירוע הדומה (event_id) אך ורק בשדה `similar_historical_events` ב-JSON עבור המנהל.
4. **בדיקת יומן ותאריכים:**
   - אם התאריך המבוקש תפוס בלוח הזמנים של החברה - סמן "date_status": "BOOKED", והסבר בנימוס שהתאריך תפוס לחלוטין תוך הצעת תאריך חלופי.
5. **סגירת עסקה ומעבר למפיק (Deal Closing & Producer Handoff):**
   - כאשר כל הפרטים סוכמו או כשהגענו להסכמה שרוצים לסגור ולהעביר את השיחה למפיק החברה: קבע "deal_closed": true.
   - במצב זה, בטיוטת המענה (draft_reply), הודע ללקוח באופן מפורש וחם: **אנחנו סוגרים ומשריינים לו את התאריך בלוח השנה שלנו**, והמפיק של החברה ייצור איתו קשר ישירות להמשך התכנון המפורט וההפקה!
6. **זיהוי תסכול / בקשת נציג:**
   - אם הלקוח מתווכח, לא מרוצה או מבקש טלפון: סמן "customer_sentiment": "ARGUMENTATIVE_OR_FRUSTRATED" או "REQUESTING_HUMAN".
7. **איסור מוחלט על אזכור מזהי אירוע (כמו EV-221) בטיוטת המענה:**
   - **חל איסור מוחלט** להזכיר מזהה אירוע טכני (כגון EV-101, EV-221 וכו') בתוך ה-`draft_reply` ללקוח! הלקוח לא יודע מה זה אומר ואין לכך מקום בהודעה אליו.
   - במקום זאת, שלב תובנות מהפקות קודמות באופן טבעי: "הפקנו לאחרונה אירוע דומה בהיקף כזה שכלל במות ומסכי לד...", ללא שום מזהה טכני.
   - אין לנקוב במחיר סופי סגור מראש (אלא טווחי מינימום לפי המדיניות או סיכום ההצעה המוסכמת).

    8. **גבולות גזרה, בטיחות קפדנית וסיווג שאלות מחוץ לתחום (Strict Safety & Scope Guardrails):**
       - אתה סוכן ייעודי אך ורק לחברת הפקות אירועים.
       - אם הלקוח שואל שאלה שאינה קשורה לחלוטין לאירועים (כגון פוליטיקה, חדשות עולם, ספורט, רכילות, בדיחות כלליות, מניות וכו'):
         * סווג את הפנייה כ-"lead_category": "NON_LEAD".
         * נסח טיוטת מענה (draft_reply) מנומסת, מקצועית ועסקית:
           "אני סוכן ייעודי להפקת אירועים של EventTriage, ואין באפשרותי לספק מידע בנושאים שאינם קשורים לתכנון והפקת האירוע שלך. נשמח לסייע בכל שאלה בנוגע לאירוע המתוכנן!"
       - **איסור מוחלט על חיפוש מחירי מתחרים:** לעולם אין לצטט מחירי הפקה של חברות אחרות ברשת. המחירונים היחידים הקובעים הם אלה שבמסמך המדיניות הפנימי של החברה.

    9. **כללי פירוט הצעת מחיר, תוספות ואיסור המצאת מחירים (Strict Quoting Rules & No Inventions):**
       - **מתי לפרט הצעת מחיר:** ספק פירוט מספרי של הצעת מחיר אך ורק אם הלקוח ביקש זאת במפורש (כגון: "תוכל לשלוח לי פירוט עלויות?", "איך מורכבת ההצעה?"). אם לא ביקש פירוט, אל תציג פירוט מפורט סתם כך.
       - **מבנה הפירוט (כאשר נדרש):** חשב בצורה מדויקת לפי המחירון הרשמי: (כמות מוזמנים × מחיר מנה בסיסי) + (תוספות רשמיות שנבחרו) + הגברה/תאורה + 18% מע"מ.
       - **הצעת שדרוגים מתוך הרשימה הרשמית בלבד:** הצע ללקוח את האפשרות לשלב שדרוגים מתוך המחירון הרשמי בלבד: שדרוג בר פרימיום וקוקטיילים (65 ₪ לאורח), עמדת שף אסאדו ומעשנת בשרים (75 ₪ לאורח), עמדת צילום מגנטים / 360 (2,500 ₪), מסכי לד ותאורת במה (6,000 ₪) או שולחן קינוחי שוק (35 ₪ לאורח). אם הלקוח מבקש תוספות אלו, חשב אותן במדויק בהצעה!
       - **חוק ברזל - איסור מוחלט על המצאת מחירים לדברים שאינם רשומים (Strict No-Invention Rule):**
         * **לסוכן אסור בשום אופן לתת הצעות מחיר על דברים שהוא לא יודע והם לא רשומים במחירון המדיניות!**
         * אך ורק שירותים ותוספות שרשומים במפורש במדיניות ניתנים לתמחור.
         * אם הלקוח מבקש דבר שאינו רשום (כגון הופעת זמר/אמן ספציפי, זיקוקין, צניחה חופשית וכד') – **אל תמציא מחיר!** ציין כי ניתן לבחון את שילוב התוספת, אך היא תיבדק ותתומחר במדויק ישירות מול מפיק החברה בשיחה טלפונית.
       - **הבהרת גמישות והמשך שיחה אנושית:** בסיום כל פירוט, הדגש תמיד כי המחיר אינו סופי, פתוח לשיח ולהתאמה לתקציב שלו, וכי אם הכיוון מתאים לו הוא יקבל שיחה אישית ממפיק החברה כדי לדייק ולסגור הכל אישית.

    10. **טיפול בפניות ספקים ונותני שירותים (Suppliers & Vendors Protocol):**
        - כאשר הפנייה מגיעה מספק שירותים, אטרקציות, צלמים, ספק מגנטים, דיג'יי, קייטרינג, הפקות תוכן וכדומה המציע שיתוף פעולה, שירותים או יצירת קשר:
          * סווג את הפנייה כ-"lead_category": "NON_LEAD" ו-"suggested_action": "TAG_AS_VENDOR".
          * בנימוק ה-AI (reasoning): ציין שמדובר בפניית ספק שירותים או הצעה לשיתוף פעולה, ולכן מדובר ב-NON_LEAD לפי מדיניות החברה.
          * בטיוטת המענה (draft_reply): נסח מענה שירותי, אדיב ומכבד: הודה על הפנייה, והפנה את הספק **באופן מפורש** לשלוח את תיק העבודות, המחירון ופרטי ההתקשרות ישירות למייל הספקים הרשמי של החברה: {config.SUPPLIERS_EMAIL}, תוך ציון כי המידע יישמר במאגר הספקים של EventTriage ונבחן שיתופי פעולה עתידיים בהתאם לצורך.

---
### הנחיות קריטיות למבנה הפלט:
עליך להחזיר אך ורק אובייקט JSON תקני ומלא לפי המבנה הבא (ללא טקסט חופשי וללא Markdown מסביב):

{{
  "lead_category": "HIGH_VALUE_B2B | STANDARD_PRIVATE | RETURNING_CLIENT | UNREALISTIC_SCOPE | AMBIGUOUS_NEED | NON_LEAD",
  "project_complexity": "LOW | MEDIUM | HIGH",
  "entities_extracted": {{
    "guest_count": "מספר או UNKNOWN",
    "event_type": "Corporate / Private / Boutique / Vendor / Unknown",
    "timeline": "תאריך או עונה",
    "stated_budget": "סכום או UNKNOWN"
  }},
  "budget_and_timeline_feasibility": "FEASIBLE | UNREALISTIC | UNKNOWN",
  "similar_historical_events": [
    {{
      "event_id": "מזהה האירוע ממאגר העבר (למשל EV-101) - לצורכי המנהל בלבד!",
      "similarity_reason": "הסבר קצר מדוע המקרה דומה מבחינת אורחים/סוג/תקציב",
      "historical_outcome": "האם הושלם בהצלחה / מחיר סגירה מקורי"
    }}
  ],
  "date_status": "AVAILABLE | BOOKED | NOT_SPECIFIED",
  "customer_sentiment": "SATISFIED_OR_NEUTRAL | ARGUMENTATIVE_OR_FRUSTRATED | REQUESTING_HUMAN",
  "deal_closed": false,
  "deal_summary": "סיכום קצר של תנאי העסקה אם deal_closed=true, אחרת ריק",
  "reasoning": "נימוק הסיווג וההיתכנות על בסיס מדיניות החברה ואירועי העבר",
  "suggested_action": "NOTIFY_PRODUCER_REVIEW | SEND_DIRECT_REPLY | SEND_PRICING_GUIDE | ASK_CLARIFICATION | ROUTE_TO_ACCOUNT_MANAGER | TAG_AS_VENDOR",
  "draft_reply": "נוסח הודעת מענה קצרה וידידותית לטלגרם (ללא אזכור מזהי אירוע EV-XXX!)"
}}"""

    def _extract_json(self, raw_text: str) -> dict:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)
        data = json.loads(cleaned)

        # אכיפה מחמירה: ניקוי כל אזכור של מזהה אירוע (כמו EV-101, EV-221) מטיוטת המענה ללקוח
        if "draft_reply" in data and isinstance(data["draft_reply"], str):
            reply = data["draft_reply"]
            # 1. ניקוי סוגריים עם מזהים: (למשל אירועים EV-101 ו-EV-407)
            reply = re.sub(r'\s*\((?:למשל\s+)?(?:ב?אירוע(?:ים)?\s*)?EV-\d+(?:(?:\s*,\s*|\s+ו-|\s+או\s+)EV-\d+)*\)', '', reply)
            # 2. ניקוי אזכורים ישירים: באירוע EV-221, או EV-101
            reply = re.sub(r'\s*(?:ב?אירוע(?:ים)?\s+)?EV-\d+', '', reply)
            # 3. ניקוי מזהים בודדים שנותרו
            reply = re.sub(r'\bEV-\d+\b', '', reply)
            reply = re.sub(r'\s{2,}', ' ', reply).strip()
            data["draft_reply"] = reply

        return data

    @staticmethod
    def _is_math_code(code_str: str) -> bool:
        """
        בודק האם הקוד שהורץ ביצע חישוב מתמטי/תמחירי אמיתי, או שרק עסק בבניית/אימות נתונים ו-JSON.
        """
        if not code_str:
            return False

        # 1. ניקוי מחרוזות והערות כדי למנוע זיהוי שגוי של תווים וטקסטים (כגון '1+1 חינם', 'Corporate / Private', שרשור טקסט וכו')
        code_no_str = re.sub(r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\')', '""', code_str)
        code_no_str = re.sub(r'#.*', '', code_no_str)

        # 2. בדיקת חישובים אריתמטיים מובהקים:
        # א. פעולות חשבון ישירות על מספרים: 100 * 65, 55000 + 6500, 69000 * 0.18
        if re.search(r'\d+(?:\.\d+)?\s*[\*\+\-\/]\s*[\d\.]+', code_no_str):
            return True
        # ב. אחוזי מע"מ או מכפלות מע"מ מפורשות: 0.18, 1.18
        if re.search(r'\b(?:0\.18|1\.18)\b', code_no_str):
            return True
        # ג. פעולות חשבון בין משתנים ומספרים: guests * 65, subtotal * 0.18, price + 500
        if re.search(r'\b[a-zA-Z_]\w*\s*[\*\+\-\/]\s*\d+', code_no_str) or re.search(r'\d+\s*[\*\+\-\/]\s*[a-zA-Z_]\w*', code_no_str):
            return True
        # ד. ביטויי חישוב תמחור ועלויות: total = base + bar + asado
        if re.search(r'\b(?:total|subtotal|price|cost|vat|budget)\s*[\+\-\*\/]?=\s*[\w\d\s\+\-\*\/]+[\+\-\*\/]', code_no_str, re.IGNORECASE):
            return True
        # ה. פונקציות סכימה וספריות מתמטיות: sum(...), math.ceil(...)
        if re.search(r'\b(?:sum|math\.\w+)\s*\(', code_no_str):
            return True

        return False

    def analyze_and_draft(self, conv: ConversationState, current_user_message: str) -> dict:
        # סינון מקדים חכם בקוד Python (0 טוקנים!) - שולף רק את ה-4 הרלוונטיים ביותר
        relevant_events = self.get_top_relevant_events(current_user_message, conv, top_k=4)
        filtered_table = self.format_filtered_history_table(relevant_events)

        history_text = conv.format_history_for_prompt()
        system_instruction = self.build_system_instruction(filtered_table)

        prompt = f"""היסטוריית השיחה עד כה:
{history_text}

הודעת הלקוח החדשה כעת:
{current_user_message}

נתח את הפנייה בהתאם להנחיות, בחר את אירועי העבר הדומים מתוך הרשימה הממוקדת, ובנה את אובייקט ה-JSON המלא:"""

        generation_config = {
            "temperature": 0.2,
            "max_output_tokens": 4096,
            "top_p": 0.95,
        }

        candidate_models = [
            "models/gemini-3.5-flash-lite",
            "models/gemini-3.6-flash",
            "models/gemini-3-flash-preview",
        ]

        # כלי פעולה אוטונומי: הרצת קוד Python (code_execution) לחישובים מדויקים ואימות נתונים
        tool_options = [
            [{"type": "code_execution"}],
            None,
        ]

        last_error = None
        for tools_to_use in tool_options:
            for model_name in candidate_models:
                try:
                    kwargs = {
                        "model": model_name,
                        "input": prompt,
                        "system_instruction": system_instruction,
                        "generation_config": generation_config,
                    }
                    if tools_to_use:
                        kwargs["tools"] = tools_to_use

                    interaction = self.client.interactions.create(**kwargs)
                    data = self._extract_json(interaction.output_text)

                    # זיהוי אוטונומי האם המודל בחר להשתמש בכלי במהלך הפנייה
                    tool_activity = []
                    if hasattr(interaction, "steps") and interaction.steps:
                        for idx, step in enumerate(interaction.steps):
                            step_type = getattr(step, "type", "")
                            logger.info(f"🔍 [Tool Activity] Step {idx}: type={step_type}")

                            if step_type == "code_execution_call":
                                # שליפה בטוחה של מחרוזת הקוד מתוך arguments (אובייקט או מילון) או מ-step ישירות
                                code_str = ""
                                args = getattr(step, "arguments", None)
                                if args is not None:
                                    if isinstance(args, dict):
                                        code_str = str(args.get("code") or "")
                                    else:
                                        code_str = str(getattr(args, "code", "") or "")
                                if not code_str:
                                    code_str = str(getattr(step, "code", "") or "")

                                logger.info(f"💻 [Code Executed]:\n{code_str}")

                                if self._is_math_code(code_str):
                                    tool_activity.append("חישוב מתמטי מדויק בקוד Python")
                                else:
                                    tool_activity.append("אימות מבנה נתונים בקוד Python")

                            elif step_type == "code_execution_result":
                                result_val = getattr(step, "result", None)
                                logger.info(f"📤 [Execution Result]: {result_val}")

                    # הסרת כפילויות תוך שמירה על הסדר
                    unique_activity = list(dict.fromkeys(tool_activity))
                    if unique_activity:
                        data["autonomous_action"] = " + ".join(unique_activity)
                    else:
                        data["autonomous_action"] = "מענה ישיר ללא צורך בכלי (החלטה אוטונומית)"

                    return data
                except Exception as e:
                    logger.warning(f"Failed with {model_name} (tools={tools_to_use}): {e}. Trying next option...")
                    last_error = e
                    time.sleep(1)

        raise last_error

gemini_service = GeminiService()
