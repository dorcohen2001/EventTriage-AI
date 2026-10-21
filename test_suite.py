import os
import sys
import json
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

print("--- 1. Testing Imports ---")
try:
    import config
    import schedule_manager
    import spam_filter
    import conversation_manager
    import gemini_service
    import Ofek
    print("SUCCESS: All modules imported without errors.")
except Exception as e:
    print(f"FAILED import: {e}")
    sys.exit(1)

print("\n--- 2. Testing Fast Pre-Filter (0 Tokens Python Filtering) ---")
gs = gemini_service.gemini_service
all_events = gs._all_historical_events
print(f"Total events in Excel memory: {len(all_events)}")
assert len(all_events) >= 100, f"Expected at least 100 events, got {len(all_events)}"

# Test pre-filtering for Corporate
top_corp = gs.get_top_relevant_events("כנס טכנולוגי ל-130 עובדים עם במות והגברה", None, top_k=3)
assert len(top_corp) == 3
assert top_corp[0]["event_type"] == "Corporate"
print(f"Top matched event: {top_corp[0]['event_id']} (Type: {top_corp[0]['event_type']}, Guests: {top_corp[0]['guest_count']})")
print("SUCCESS: Pre-filtering accurately retrieved top 3 corporate events out of 106!")

print("\n--- 3. Testing Commercial Spam Filter ---")
sf = spam_filter.SpamFilter()
is_spam, reason = sf.is_spam(12345, "אם אתה רוצה לקנות דברים שווים רק אצלנו ברמי לוי")
assert is_spam == True
assert "NON_LEAD" in reason
is_spam_legit, _ = sf.is_spam(12345, "שלום אנחנו רוצים להפיק כנס חברה של 100 איש")
assert is_spam_legit == False
print("SUCCESS: Commercial spam filter working correctly.")

print("\n--- 4. Testing Gemini Similarity Layer with Filtered Prompt ---")
cm = conversation_manager.ConversationManager()
test_conv = cm.get_or_create(99999, user_id=42, user_name="רון לוי")

sample_inquiry = "היי, אנחנו חברת סטארטאפ של 130 עובדים ומחפשים להפיק כנס טכנולוגי שנתי עם במות והגברה בתקציב של כ-70 אלף ש\"ח לעוד חודשיים"
print(f"Sending test inquiry to Gemini with pre-filtered events: '{sample_inquiry}'...")

res = gs.analyze_and_draft(test_conv, sample_inquiry)
print("Gemini result:")
print(json.dumps(res, indent=2, ensure_ascii=False))

assert "lead_category" in res
assert "project_complexity" in res
assert "similar_historical_events" in res
assert len(res["similar_historical_events"]) >= 1
assert "draft_reply" in res

print(f"\nMatched Event ID: {res['similar_historical_events'][0]['event_id']}")
print(f"Draft Reply: {res['draft_reply']}")

print("\n--- 5. Testing Image Showcase & Concept Gallery ---")
import image_service
img_srv = image_service.image_service
img_res = img_srv.get_event_images(
    event_type=res.get("entities_extracted", {}).get("event_type", "Corporate"),
    user_text=sample_inquiry,
    similar_events=res.get("similar_historical_events", [])
)
assert img_res is not None, "Image showcase result should not be None"
assert len(img_res["image_paths"]) == 2, f"Expected 2 showcase images, got {len(img_res['image_paths'])}"
print(f"SUCCESS: Concept Matched: {img_res['concept_key']} ({img_res['title']})")
print(f"Showcase Image Paths: {img_res['image_paths']}")

print("\n--- 6. Testing No-EV-in-Drafts & Auto-Booking on Deal Close ---")
# א. וידוא שאין מזהי אירוע בטיוטה
assert "EV-" not in res.get("draft_reply", ""), f"EV ID found in draft reply: {res.get('draft_reply')}"

# ב. בדיקת סינון ידני במקרה ש-Gemini היה מחזיר EV-XXX
dummy_json = '''{
  "draft_reply": "היי! הפקנו אירוע דומה (למשל אירועים EV-101 ו-EV-407) וגם באירוע EV-221 היה מושלם.",
  "similar_historical_events": [{"event_id": "EV-101"}]
}'''
cleaned = gs._extract_json(dummy_json)
assert "EV-" not in cleaned["draft_reply"], f"Regex failed to scrub EV ID: {cleaned['draft_reply']}"
print(f"Scrubbed Draft Reply: {cleaned['draft_reply']}")

# ג. בדיקת סגירת תאריך בלוח השנה
initial_events = len(schedule_manager.schedule_manager.get_booked_events())
test_booking_date = "2026-12-25"
schedule_manager.schedule_manager.book_new_event(
    date=test_booking_date,
    event_type="Corporate",
    guest_count=150,
    price=85000,
    title="אירוע חברה סוף שנה - בדיקה"
)
is_booked, booked_ev = schedule_manager.schedule_manager.is_date_booked(test_booking_date)
assert is_booked == True
print(f"Schedule booked event for {test_booking_date}: {booked_ev['title']}")

print("\n--- 7. Testing Supplier / Vendor Inquiry (NON_LEAD) & Email Routing ---")
vendor_inquiry = "היי אני ספק מגנטים\nרוצה ליצור איתכם קשר!"
vendor_conv = cm.get_or_create(88888, user_id=99, user_name="יוסי מגנטים")
vendor_res = gs.analyze_and_draft(vendor_conv, vendor_inquiry)
print("Vendor Gemini result:")
print(json.dumps(vendor_res, indent=2, ensure_ascii=False))

assert vendor_res.get("lead_category") == "NON_LEAD", f"Expected NON_LEAD, got {vendor_res.get('lead_category')}"
assert "EventTriage@gmail.com" in vendor_res.get("draft_reply", ""), f"Expected EventTriage@gmail.com in draft reply: {vendor_res.get('draft_reply')}"
print("SUCCESS: Supplier inquiry correctly classified as NON_LEAD and routed to EventTriage@gmail.com!")

print("\n🎉 ALL ADVANCED TESTS PASSED (ZERO EV-IDs IN DRAFTS + SCHEDULE AUTO-BOOKING + VENDOR EMAIL ROUTING)! 🎉")


