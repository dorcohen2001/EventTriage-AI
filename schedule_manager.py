import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import config

logger = logging.getLogger(__name__)

class ScheduleManager:
    def __init__(self, schedule_file: Path = config.SCHEDULE_FILE):
        self.schedule_file = Path(schedule_file)
        self._ensure_file()

    def _ensure_file(self):
        if not self.schedule_file.exists():
            default_data = {
                "company_name": config.COMPANY_NAME,
                "booked_events": []
            }
            self._save(default_data)

    def _load(self) -> dict:
        try:
            with open(self.schedule_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading schedule file: {e}")
            return {"company_name": config.COMPANY_NAME, "booked_events": []}

    def _save(self, data: dict):
        try:
            with open(self.schedule_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving schedule file: {e}")

    def get_booked_events(self) -> List[dict]:
        data = self._load()
        return data.get("booked_events", [])

    def get_booked_dates_summary_for_prompt(self) -> str:
        events = self.get_booked_events()
        if not events:
            return "כרגע אין תאריכים תפוסים בלוח הזמנים. כל התאריכים פנויים (בכפוף לזמן היערכות)."

        lines = ["📅 **לוח תאריכים תפוסים של החברה (בתאריכים אלו אין מקום לאירוע נוסף):**"]
        for ev in events:
            date = ev.get("date", "לא צוין")
            title = ev.get("title", "אירוע סגור")
            ev_type = ev.get("event_type", "")
            lines.append(f"- תאריך: {date} | סוג: {ev_type} ({title}) - תפוס לחלוטין")
        lines.append("הנחיה חשובה: אם הלקוח מבקש אחד מתאריכים אלו, עליך להודיע לו באופן ברור ונעים שהחברה תפוסה בתאריך זה, ולהציע לו לבחון תאריכים חלופיים.")
        return "\n".join(lines)

    def is_date_booked(self, target_date_str: str) -> Tuple[bool, Optional[dict]]:
        """
        בודק אם תאריך מסוים תפוס.
        """
        events = self.get_booked_events()
        target_clean = target_date_str.strip().lower()
        for ev in events:
            ev_date = str(ev.get("date", "")).strip().lower()
            if target_clean == ev_date or (target_clean and target_clean in ev_date):
                return True, ev
        return False, None

    def book_new_event(self, date: str, event_type: str, guest_count: int, price: float, title: str = "", notes: str = "") -> dict:
        """
        סוגר אירוע ומוסיף אותו ליומן החברה.
        """
        data = self._load()
        new_event = {
            "date": date,
            "event_type": event_type,
            "title": title or f"אירוע {event_type} - {guest_count} אורחים",
            "guest_count": guest_count,
            "price": price,
            "notes": notes,
            "booked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        data.setdefault("booked_events", []).append(new_event)
        self._save(data)
        logger.info(f"Event booked successfully for date {date}: {new_event}")
        return new_event

schedule_manager = ScheduleManager()
