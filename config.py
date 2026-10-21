import os
from pathlib import Path

# File paths
BASE_DIR = Path(__file__).resolve().parent
POLICY_FILE = BASE_DIR / "events_pricing_and_rules.md"
SCHEDULE_FILE = BASE_DIR / "company_schedule.json"
HISTORY_FILE = BASE_DIR / "event_leads_history.xlsx"

# Automatically load environment variables from .env file if it exists
_ENV_FILE = BASE_DIR / ".env"
if _ENV_FILE.exists():
    with open(_ENV_FILE, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# Telegram and AI keys (configured via .env or system environment)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
LEADS_CHAT_ID = int(os.getenv("LEADS_CHAT_ID", "0"))
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Contact info for escalation
COMPANY_NAME = "EventTriage הפקות אירועים"
COMPANY_PHONE = "050-8889999"
COMPANY_EMAIL = "EventTriage@gmail.com"
SUPPLIERS_EMAIL = "EventTriage@gmail.com"

# Anti-spam & token saving rules
SPAM_WINDOW_SECONDS = 8           # Time window in seconds
SPAM_MAX_MESSAGES_IN_WINDOW = 3   # Max messages in time window
MAX_REPEATED_MESSAGES = 2         # Max identical messages in a row
MIN_MESSAGE_LENGTH = 2            # Minimum length of message
MAX_CONVERSATION_TURNS = 25       # Max turns before prompting direct contact
