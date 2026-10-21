import os
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

ASSETS_IMAGES_DIR = Path(__file__).parent / "assets" / "images"

CONCEPTS = {
    "corporate_tech": {
        "title": "כנס והרמת כוסית הייטק יוקרתית",
        "description": "במות ממותגות, מסכי לד פנורמיים, תאורה עתידנית ועמדות מינגלינג יוקרתיות",
        "files": ["corporate_tech_1.jpg", "corporate_tech_2.jpg"]
    },
    "corporate_beach": {
        "title": "מסיבת חוף ופסטיבל קיץ לחברה",
        "description": "מתחמי רביצה בוהו-שיק על קו המים, במת דיג'יי ותאורת שקיעה מהפנטת",
        "files": ["corporate_beach_1.jpg", "corporate_beach_2.jpg"]
    },
    "corporate_gala": {
        "title": "אירוע גאלה ויקב פרימיום / גג אורבני",
        "description": "ארוחת שף יוקרתית בין הכרמים או על גג פנורמי, תאורת אווירה חמימה וסומלייה",
        "files": ["corporate_gala_1.jpg", "corporate_gala_2.jpg"]
    },
    "private_forest": {
        "title": "חתונת טבע ביער / אירוע שטח פתוח",
        "description": "חופה פרחונית בטבע, אלפי נורות פיות בין העצים, ריהוט כפרי מעץ מלא והרכב מוזיקלי חי",
        "files": ["private_forest_1.jpg", "private_forest_2.jpg"]
    },
    "private_villa": {
        "title": "אירוע יוקרה בווילה פרטית עם בריכה ואסאדו",
        "description": "מתחם בריכה מואר, לאונג' יוקרתי, עמדת שף בשרים ומעשנות פרימיום ובר קוקטיילים",
        "files": ["private_villa_1.jpg", "private_villa_2.jpg"]
    },
    "private_celebration": {
        "title": "בר/בת מצווה ומסיבת קונספט יוקרתית",
        "description": "תאורת ניאון ולייזר, במת דיג'יי מועדונית, עמדות צילום ממותגות ואווירה אנרגטית",
        "files": ["private_celebration_1.jpg", "private_celebration_2.jpg"]
    },
    "boutique_chef": {
        "title": "ארוחת שף אינטימית ושולחן אבירים בוטיק",
        "description": "שולחן אבירים מעוצב בנרות ופרחים, מנות גורמה בהרכבה אישית של שף פרטי ובר קוקטיילים",
        "files": ["boutique_chef_1.jpg", "boutique_chef_2.jpg"]
    }
}


class ImageService:
    def __init__(self, images_dir: Path = ASSETS_IMAGES_DIR):
        self.images_dir = images_dir
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def match_concept(
        self,
        event_type: Optional[str] = None,
        user_text: str = "",
        similar_events: Optional[List[dict]] = None
    ) -> str:
        text = user_text.lower()
        sim_text = ""
        if similar_events:
            for ev in similar_events:
                sim_text += " " + str(ev.get("similarity_reason", "")).lower()
                sim_text += " " + str(ev.get("historical_notes", "")).lower()
                sim_text += " " + str(ev.get("event_id", "")).lower()

        combined = f"{text} {sim_text}".lower()

        import re
        def has_words(words, target_str):
            for w in words:
                pattern = r'(?:\b|(?<=\s)|(?<=^))' + re.escape(w) + r'(?:\b|(?=\s)|(?=$)|(?=[.,!?]))'
                if re.search(pattern, target_str):
                    return True
            return False

        # 1. חוף וקיץ
        if has_words(["חוף", "ים", "חופי", "קיץ", "בריזה", "סאפ", "גלשן", "חול", "בגד ים"], combined):
            return "corporate_beach"

        # 2. טבע ויער / חתונה כפרית
        if has_words(["יער", "חורש", "טבע", "חתונה", "חופה", "כפרי", "שדות", "מטע"], combined):
            return "private_forest"

        # 3. וילה / בריכה / אסאדו
        if has_words(["וילה", "בריכה", "אסאדו", "מעשנה", "מעשנות", "בשרים", "בריכת"], combined):
            return "private_villa"

        # 4. יקב / גג / גאלה
        if has_words(["יקב", "כרם", "יין", "גג", "רופטופ", "rooftop", "גאלה", "הנהלה"], combined):
            return "corporate_gala"

        # 5. בר/בת מצווה / מסיבת נוער
        if has_words(["בר מצווה", "בת מצווה", "בר/בת", "ניאון", "מתבגרים", "טיקטוק", "גלמפינג", "מדבר"], combined):
            return "private_celebration"

        # 6. בוטיק / שף אינטימי
        if has_words(["שף", "אבירים", "אינטימי", "טעימות", "בוטיק", "יום הולדת", "יומולדת", "רווקות"], combined):
            return "boutique_chef"

        # 7. כנס / הייטק
        if has_words(["כנס", "כנסים", "הייטק", "במות", "מסכי לד", "הרמת כוסית", "חברה", "עובדים"], combined):
            return "corporate_tech"

        # ברירות מחדל לפי סוג אירוע
        if event_type == "Corporate":
            return "corporate_tech"
        elif event_type == "Private":
            return "private_villa"
        elif event_type == "Boutique":
            return "boutique_chef"

        return "corporate_tech"

    def get_event_images(
        self,
        event_type: Optional[str] = None,
        user_text: str = "",
        similar_events: Optional[List[dict]] = None
    ) -> Optional[dict]:
        concept_key = self.match_concept(event_type, user_text, similar_events)
        concept_info = CONCEPTS.get(concept_key)
        if not concept_info:
            return None

        paths = []
        for fn in concept_info["files"]:
            p = self.images_dir / fn
            if p.exists():
                paths.append(str(p.resolve()))

        if not paths:
            return None

        return {
            "concept_key": concept_key,
            "title": concept_info["title"],
            "description": concept_info["description"],
            "image_paths": paths
        }


image_service = ImageService()
