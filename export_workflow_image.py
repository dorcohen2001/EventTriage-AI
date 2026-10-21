import httpx
import os

clean_mermaid = """graph TD
    ClientMsg["הודעת לקוח חדשה בצ'אט הלידים"] --> Listener["Ofek.py (מאזין טלגרם)"]

    Listener --> CheckEnd{"האם הלקוח כתב<br/>'סיימתי את השיחה'?"}
    CheckEnd -- כן --> EndConv["איפוס השיחה וסגירת זיכרון"]
    CheckEnd -- לא --> SpamCheck

    subgraph Layer1 ["שכבה 1: סינון ספאם והצפה (0 טוקנים)"]
        SpamCheck{"האם זוהה ספאם?<br/>(הצפה / ג'יבריש / ספק מסחרי)"}
        SpamCheck -- "כן (ספאם)" --> SpamAlert["התראת ספאם בערוץ המנהל<br/>(אפשרות שחרור או חסימה)"]
        SpamAlert -- "מנהל אישר כליד תקין" --> PreFilter
    end

    SpamCheck -- "לא (ליד תקין)" --> PreFilter

    subgraph Layer2 ["שכבה 2: סינון מקדים וזמינות יומן (0 טוקנים)"]
        PreFilter["סינון מקדים חכם בזיכרון Python<br/>סריקת 106 אירועים מ-Excel ודירוג התאמה"]
        PreFilter --> TopCandidates["שליפת 3-4 האירועים הכי דומים בלבד<br/>(חיסכון של 95% בטוקנים)"]
        TopCandidates --> CalCheck["בדיקת יומן החברה<br/>(schedule_manager מול company_schedule.json)"]
    end

    subgraph Layer3 ["שכבה 3: ניתוח עמוק ב-Gemini AI"]
        CalCheck --> GeminiCall["קריאה ממוקדת ל-Gemini Flash<br/>חילוץ ישויות, היתכנות ומציאת אירועי עבר"]
        GeminiCall --> ScrubEngine["מנוע טיוטות נקיות<br/>איסור וניקוי מזהי EV-XXX מטיוטת הלקוח"]
        ScrubEngine --> ImageMatch["התאמת תמונות קונספט (image_service)<br/>שליפת צמד תמונות הדגמה ברמת 8K"]
    end

    subgraph Layer4 ["שכבה 4: מרכז בקרה ואישור מנהל (Admin Chat)"]
        ImageMatch --> AdminCard["כרטיס ניתוח מלא למנהל:<br/>• סיווג ליד ורמת מורכבות<br/>• אירועי עבר, דמיון ואחוזי רווחיות<br/>• תמונות המחשה זמינות<br/>• טיוטת מענה מוצעת נקייה ממזהים"]

        AdminCard --> AdminAction{"בחירת פעולת מנהל"}
        AdminAction -- "אשר ושלח + 2 תמונות" --> SendAlbum["שליחת מענה + אלבום תמונות ללקוח"]
        AdminAction -- "שלח טקסט בלבד" --> SendText["שליחת טקסט בלבד ללקוח"]
        AdminAction -- "ערוך טיוטה" --> EditDraft["עריכת הטקסט ישירות בצ'אט הניהול"]
        AdminAction -- "שתף טלפון" --> SendPhone["שליחת טלפון/ווטסאפ ללקוח"]
        AdminAction -- "אשר סגירת עסקה" --> CloseDeal["שריון תאריך ביומן החברה<br/>והודעה ללקוח שהמפיק ימשיך מולו!"]
        AdminAction -- "דחה" --> Reject["מחיקת הפנייה ללא שליחה"]
    end

    SendAlbum --> UpdateMemory["עדכון היסטוריית השיחה (conversation_manager)"]
    SendText --> UpdateMemory
    SendPhone --> UpdateMemory
    CloseDeal --> UpdateMemory
    EditDraft --> AdminCard
"""

def generate():
    r = httpx.post(
        "https://kroki.io/mermaid/png",
        content=clean_mermaid.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
        timeout=20.0
    )
    print("Kroki status:", r.status_code, "Length:", len(r.content))
    if r.status_code == 200:
        local_path = os.path.abspath("workflow_diagram.png")
        with open(local_path, "wb") as f:
            f.write(r.content)
        
        artifact_path = r"C:\Users\Dor\.gemini\antigravity\brain\b96d3484-9d61-40a0-94d5-1499dcd56a4c\workflow_diagram.png"
        with open(artifact_path, "wb") as f:
            f.write(r.content)
            
        print("Updated both local and artifact workflow_diagram.png successfully!")
    else:
        print("Failed:", r.text[:200])

if __name__ == "__main__":
    generate()
