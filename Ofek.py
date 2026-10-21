import html
import json
import logging
import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from conversation_manager import conversation_manager
from gemini_service import gemini_service
from schedule_manager import schedule_manager
from spam_filter import spam_filter
from image_service import image_service

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

async def safe_send_media_group(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    image_paths: list,
    caption: str = None,
    reply_to_message_id: int = None,
):
    """
    שולח אלבום תמונות (Media Group) בבטחה תוך סגירה נאותה של הקבצים.
    """
    files = []
    try:
        media = []
        for idx, path in enumerate(image_paths):
            f = open(path, "rb")
            files.append(f)
            if idx == 0 and caption:
                media.append(InputMediaPhoto(media=f, caption=caption, parse_mode="HTML"))
            else:
                media.append(InputMediaPhoto(media=f))
        return await context.bot.send_media_group(
            chat_id=chat_id,
            media=media,
            reply_to_message_id=reply_to_message_id,
        )
    except Exception as e:
        logger.error(f"Error sending media group: {e}")
        return None
    finally:
        for f in files:
            try:
                f.close()
            except Exception:
                pass

# זיכרון זמני לבקשות הממתינות לפעולת מנהל
pending_approvals = {}
# זיכרון זמני להודעות ספאם הממתינות לבדיקת מנהל
pending_spam = {}
# מעקב אחר מנהלים שנמצאים כרגע במצב עריכת טיוטה: admin_user_id -> req_key
awaiting_draft_edit = {}


async def safe_send_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    reply_markup=None,
    reply_to_message_id=None,
    parse_mode="HTML"
):
    """
    שולח הודעה בבטחה. אם נכשל בגלל שגיאת פירסור תגיות, שולח כטקסט פשוט ללא עיצוב.
    """
    try:
        return await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
            parse_mode=parse_mode,
        )
    except TelegramError as e:
        logger.warning(f"Failed to send message with parse_mode={parse_mode}: {e}. Retrying as plain text.")
        plain_text = re.sub(r"<[^>]+>", "", text)
        return await context.bot.send_message(
            chat_id=chat_id,
            text=plain_text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )


async def safe_edit_message_text(
    query,
    text: str,
    reply_markup=None,
    parse_mode="HTML"
):
    """
    עורך הודעה בבטחה עם fallback לטקסט פשוט.
    """
    try:
        return await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TelegramError as e:
        logger.warning(f"Failed to edit message with parse_mode={parse_mode}: {e}. Retrying as plain text.")
        plain_text = re.sub(r"<[^>]+>", "", text)
        return await query.edit_message_text(
            text=plain_text,
            reply_markup=reply_markup,
        )


def build_admin_card_keyboard(req_key: str, deal_closed: bool = False, sentiment: str = "SATISFIED_OR_NEUTRAL", has_images: bool = False):
    keyboard = []

    if deal_closed:
        keyboard.append([
            InlineKeyboardButton("🎉 אשר סגירת עסקה והוסף ליומן", callback_data=f"close_deal:{req_key}")
        ])
        if has_images:
            keyboard.append([
                InlineKeyboardButton("✅ אשר + 2 תמונות הדגמה 🖼️", callback_data=f"approve_photos:{req_key}"),
                InlineKeyboardButton("💬 טיוטה בלבד", callback_data=f"approve:{req_key}"),
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("✅ אשר טיוטה בלבד", callback_data=f"approve:{req_key}")
            ])
        keyboard.append([
            InlineKeyboardButton("✏️ ערוך טיוטה", callback_data=f"edit_draft:{req_key}"),
            InlineKeyboardButton("❌ דחה", callback_data=f"reject:{req_key}"),
        ])
    elif sentiment in ["ARGUMENTATIVE_OR_FRUSTRATED", "REQUESTING_HUMAN"]:
        keyboard.append([
            InlineKeyboardButton("📞 שתף טלפון לשיחה ישירה", callback_data=f"share_phone:{req_key}")
        ])
        if has_images:
            keyboard.append([
                InlineKeyboardButton("✅ אשר + 2 תמונות 🖼️", callback_data=f"approve_photos:{req_key}"),
                InlineKeyboardButton("💬 אשר טיוטה בלבד", callback_data=f"approve:{req_key}"),
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("✅ אשר טיוטה", callback_data=f"approve:{req_key}")
            ])
        keyboard.append([
            InlineKeyboardButton("✏️ ערוך טיוטה", callback_data=f"edit_draft:{req_key}"),
            InlineKeyboardButton("❌ דחה", callback_data=f"reject:{req_key}"),
        ])
    else:
        if has_images:
            keyboard.append([
                InlineKeyboardButton("✅ אשר ושלח + 2 תמונות הדגמה 🖼️", callback_data=f"approve_photos:{req_key}")
            ])
            keyboard.append([
                InlineKeyboardButton("💬 שלח טקסט בלבד", callback_data=f"approve:{req_key}"),
                InlineKeyboardButton("✏️ ערוך טיוטה", callback_data=f"edit_draft:{req_key}"),
                InlineKeyboardButton("❌ דחה", callback_data=f"reject:{req_key}"),
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("✅ אשר ושלח ללקוח", callback_data=f"approve:{req_key}"),
                InlineKeyboardButton("✏️ ערוך טיוטה", callback_data=f"edit_draft:{req_key}"),
                InlineKeyboardButton("❌ דחה", callback_data=f"reject:{req_key}"),
            ])

    return InlineKeyboardMarkup(keyboard)


async def send_admin_card(context: ContextTypes.DEFAULT_TYPE, req_key: str, conv, user, user_text: str, result_json: dict, image_info: dict = None):
    draft = result_json.get("draft_reply", "שלום, קיבלנו את פנייתך ונחזור בהקדם.")
    category = result_json.get("lead_category", "UNKNOWN")
    complexity = result_json.get("project_complexity", "MEDIUM")
    date_status = result_json.get("date_status", "NOT_SPECIFIED")
    sentiment = result_json.get("customer_sentiment", "SATISFIED_OR_NEUTRAL")
    deal_closed = bool(result_json.get("deal_closed", False))
    reasoning = result_json.get("reasoning", "")
    similar_events = result_json.get("similar_historical_events", [])

    deal_progress = conversation_manager.get_deal_summary(conv)

    if deal_closed:
        status_header = "🎉 <b>זוהתה סגירת עסקה! כל הפרטים סוכמו!</b>"
    elif sentiment in ["ARGUMENTATIVE_OR_FRUSTRATED", "REQUESTING_HUMAN"]:
        status_header = "⚠️ <b>שים לב: הלקוח אינו מרוצה או מבקש מענה אנושי!</b>"
    elif conv.turn_count == 0:
        status_header = "🌟 <b>פנייה חדשה מלקוח (התחלת שיחה חדשה)</b>"
    else:
        status_header = f"💬 <b>הודעה נוספת בשיחה רציפה (סבב #{conv.turn_count + 1})</b>"

    client_name = html.escape(user.full_name if user else "אנונימי")
    escaped_cat = html.escape(str(category))
    escaped_comp = html.escape(str(complexity))
    escaped_date_status = html.escape(str(date_status))
    escaped_progress = html.escape(deal_progress)
    escaped_user_text = html.escape(user_text)
    escaped_reasoning = html.escape(str(reasoning))
    escaped_draft = html.escape(str(draft))

    # עיצוב שכבת דמיון לאירועי עבר
    similar_lines = []
    for ev in similar_events:
        ev_id = html.escape(str(ev.get("event_id", "")))
        ev_reason = html.escape(str(ev.get("similarity_reason", "")))
        ev_out = html.escape(str(ev.get("historical_outcome", "")))
        similar_lines.append(f"• <b>{ev_id}</b>: {ev_reason} (<i>{ev_out}</i>)")
    similar_summary = "\n".join(similar_lines) if similar_lines else "לא נמצאו אירועים דומים ישירים"

    # תמונות המחשה
    image_section = ""
    has_images = False
    if image_info and image_info.get("image_paths"):
        has_images = True
        img_title = html.escape(image_info["title"])
        img_desc = html.escape(image_info["description"])
        image_section = f"🖼️ <b>תמונות המחשה זמינות ({len(image_info['image_paths'])}):</b> {img_title}\n<i>{img_desc}</i>\n\n"

    autonomous_action = result_json.get("autonomous_action")
    autonomous_line = f"🤖 <b>פעולה אוטונומית:</b> <code>{html.escape(str(autonomous_action))}</code>\n\n" if autonomous_action else ""

    admin_message = (
        f"{status_header}\n\n"
        f"👤 <b>לקוח:</b> {client_name}\n"
        f"🏷 <b>סיווג:</b> <code>{escaped_cat}</code> | <b>מורכבות:</b> <code>{escaped_comp}</code> | <b>יומן:</b> <code>{escaped_date_status}</code>\n\n"
        f"📊 <b>מצב פרטי האירוע שנאספו:</b>\n{escaped_progress}\n\n"
        f"🔍 <b>אירועי עבר דומים ממאגר החברה (Similarity Layer):</b>\n{similar_summary}\n\n"
        f"{image_section}"
        f"💬 <b>הודעת הלקוח:</b>\n<i>{escaped_user_text}</i>\n\n"
        f"{autonomous_line}"
        f"🧠 <b>נימוק ה-AI:</b>\n{escaped_reasoning}\n\n"
        f"✉️ <b>טיוטת תגובה מוצעת (ניתן לערוך):</b>\n{escaped_draft}"
    )

    reply_markup = build_admin_card_keyboard(req_key, deal_closed=deal_closed, sentiment=sentiment, has_images=has_images)

    await safe_send_message(
        context=context,
        chat_id=config.ADMIN_CHAT_ID,
        text=admin_message,
        reply_markup=reply_markup,
        parse_mode="HTML",
    )


async def handle_incoming_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    user_text = update.message.text.strip()
    user = update.effective_user
    orig_msg_id = update.message.message_id

    # -------------------------------------------------------------
    # מקרה 1: הודעה בצ'אט הניהול (ADMIN_CHAT_ID)
    # -------------------------------------------------------------
    if chat_id == config.ADMIN_CHAT_ID:
        # בדיקה האם מנהל זה נמצא במצב עריכת טיוטה
        if user and user.id in awaiting_draft_edit:
            req_key = awaiting_draft_edit.pop(user.id)
            req_data = pending_approvals.get(req_key)
            if req_data:
                req_data["draft_reply"] = user_text
                keyboard = [
                    [InlineKeyboardButton("✅ אשר ושלח את הנוסח החדש ללקוח", callback_data=f"approve:{req_key}")],
                    [
                        InlineKeyboardButton("✏️ ערוך שוב", callback_data=f"edit_draft:{req_key}"),
                        InlineKeyboardButton("❌ דחה", callback_data=f"reject:{req_key}"),
                    ]
                ]
                escaped_new_draft = html.escape(user_text)
                await safe_send_message(
                    context=context,
                    chat_id=config.ADMIN_CHAT_ID,
                    text=f"✅ <b>הטיוטה עודכנה בהצלחה!</b>\n\n✉️ <b>הנוסח החדש שיישלח ללקוח:</b>\n{escaped_new_draft}",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    reply_to_message_id=orig_msg_id,
                    parse_mode="HTML",
                )
                return

        # בדיקה האם מנהל כתב "סיימתי את השיחה"
        if "סיימתי את השיחה" in user_text:
            ended_conv = conversation_manager.end_conversation(config.LEADS_CHAT_ID, reason="ENDED_BY_ADMIN")
            to_clear = [k for k in list(pending_approvals.keys()) if k.startswith(f"{config.LEADS_CHAT_ID}_")]
            for k in to_clear:
                pending_approvals.pop(k, None)
            to_clear_spam = [k for k in list(pending_spam.keys()) if k.startswith(f"{config.LEADS_CHAT_ID}_")]
            for k in to_clear_spam:
                pending_spam.pop(k, None)

            if ended_conv:
                spam_filter.reset_user(ended_conv.user_id)
                await safe_send_message(
                    context=context,
                    chat_id=config.LEADS_CHAT_ID,
                    text="נציג החברה סיים ואיפס את השיחה. הפנייה הבאה תטופל כשיחה חדשה לחלוטין! תודה רבה ונשמח לעמוד לשירותך שוב! 🌟",
                )
                await update.message.reply_text("✅ השיחה מול הלקוח בצ'אט הלידים אופסה לחלוטין וחזרה להתחלה (0 סבבים).")
            else:
                await update.message.reply_text("ℹ️ אין כרגע שיחה פעילה בצ'אט הלידים (השיחה כבר במצב התחלתי).")
        return

    # -------------------------------------------------------------
    # מקרה 2: הודעה בצ'אט הלידים (LEADS_CHAT_ID)
    # -------------------------------------------------------------
    if chat_id == config.LEADS_CHAT_ID:
        # בדיקה א': סיום ואיפוס שיחה יזום על ידי הלקוח
        is_reset_text = any(phrase in user_text for phrase in [
            "סיימתי את השיחה",
            "סיימתי שיחה",
            "לסיים את השיחה",
            "לסיים שיחה",
            "סיימנו את השיחה",
            "איפוס שיחה"
        ])
        if is_reset_text:
            ended_conv = conversation_manager.end_conversation(chat_id, reason="ENDED_BY_CUSTOMER")
            if user:
                spam_filter.reset_user(user.id)
            to_clear = [k for k in list(pending_approvals.keys()) if k.startswith(f"{chat_id}_")]
            for k in to_clear:
                pending_approvals.pop(k, None)
            to_clear_spam = [k for k in list(pending_spam.keys()) if k.startswith(f"{chat_id}_")]
            for k in to_clear_spam:
                pending_spam.pop(k, None)

            await update.message.reply_text(
                "תודה רבה! השיחה אופסה והסתיימה בהצלחה.\nההודעה הבאה שלך תטופל כפנייה חדשה לגמרי מההתחלה (סבב ראשון). נשמח לעמוד לשירותך בכל עת! 🌟"
            )
            await safe_send_message(
                context=context,
                chat_id=config.ADMIN_CHAT_ID,
                text="🔄 <b>השיחה אופסה לבקשת הלקוח!</b> כל היסטוריית השיחה, פרטי העסקה והסבבים נמחקו וחזרו להתחלה (0 סבבים).",
                parse_mode="HTML",
            )
            return

        # בדיקה ב': מנגנון קוד למניעת ספאם ובזבוז טוקנים
        conv = conversation_manager.get_or_create(
            chat_id=chat_id,
            user_id=user.id if user else 0,
            user_name=user.full_name if user else "לקוח",
        )

        is_spam, spam_msg = spam_filter.is_spam(
            user_id=user.id if user else 0,
            text=user_text,
            current_turn_count=conv.turn_count,
        )

        req_key = f"{chat_id}_{orig_msg_id}"

        if is_spam:
            logger.warning(f"Spam detected from user {user.id if user else 'unknown'}: {spam_msg}")
            pending_spam[req_key] = {
                "chat_id": chat_id,
                "reply_to_message_id": orig_msg_id,
                "user_id": user.id if user else 0,
                "user_name": user.full_name if user else "לקוח",
                "user_text": user_text,
                "spam_msg": spam_msg,
            }

            spam_keyboard = [
                [InlineKeyboardButton("🔓 זו לא הודעת ספאם - המשך טיפול כרגיל", callback_data=f"unmark_spam:{req_key}")],
                [
                    InlineKeyboardButton("🚫 אשר כספאם ושלח אזהרה ללקוח", callback_data=f"confirm_spam:{req_key}"),
                    InlineKeyboardButton("🗑️ התעלם ומחק", callback_data=f"dismiss_spam:{req_key}"),
                ]
            ]
            escaped_sender = html.escape(user.full_name if user else "אנונימי")
            escaped_msg = html.escape(user_text)
            escaped_reason = html.escape(spam_msg)

            admin_spam_alert = (
                f"🚨 <b>התראת ספאם / ספק: זוהתה הודעה חשודה!</b>\n\n"
                f"👤 <b>שולח:</b> {escaped_sender}\n"
                f"💬 <b>תוכן ההודעה:</b>\n<i>{escaped_msg}</i>\n\n"
                f"⚠️ <b>סיבת הזיהוי בקוד:</b> {escaped_reason}\n\n"
                f"אם המערכת שגתה ומדובר בהודעה לגיטימית, לחץ על 'זו לא הודעת ספאם'."
            )
            await safe_send_message(
                context=context,
                chat_id=config.ADMIN_CHAT_ID,
                text=admin_spam_alert,
                reply_markup=InlineKeyboardMarkup(spam_keyboard),
                parse_mode="HTML",
            )
            return

        # בדיקה ג': שליחה ל-Gemini וניתוח השיחה
        try:
            result_json = gemini_service.analyze_and_draft(conv, user_text)
        except Exception as e:
            logger.error(f"Error in Gemini analysis: {e}")
            await safe_send_message(
                context=context,
                chat_id=config.ADMIN_CHAT_ID,
                text=f"⚠️ שגיאה בעיבוד הודעת הלקוח ב-AI:\n{html.escape(str(e))}",
                parse_mode="HTML",
            )
            return

        draft = result_json.get("draft_reply", "שלום, קיבלנו את פנייתך ונחזור בהקדם.")
        entities = result_json.get("entities_extracted", {})
        sentiment = result_json.get("customer_sentiment", "SATISFIED_OR_NEUTRAL")
        deal_closed = bool(result_json.get("deal_closed", False))
        deal_summary = result_json.get("deal_summary", "")

        conv.update_deal(entities)

        image_info = image_service.get_event_images(
            event_type=entities.get("event_type"),
            user_text=user_text,
            similar_events=result_json.get("similar_historical_events", []),
        )

        pending_approvals[req_key] = {
            "chat_id": chat_id,
            "reply_to_message_id": orig_msg_id,
            "draft_reply": draft,
            "user_text": user_text,
            "entities": entities,
            "deal_closed": deal_closed,
            "deal_summary": deal_summary,
            "sentiment": sentiment,
            "image_info": image_info,
        }

        await send_admin_card(context, req_key, conv, user, user_text, result_json, image_info=image_info)


async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, req_key = query.data.split(":", 1)
    admin_user = update.effective_user

    # -------------------------------------------------------------
    # טיפול בהתראות ספאם
    # -------------------------------------------------------------
    if action == "unmark_spam":
        spam_data = pending_spam.pop(req_key, None)
        if not spam_data:
            await query.edit_message_text("פניית ספאם זו כבר טופלה או פג תוקפה.")
            return

        await safe_edit_message_text(
            query=query,
            text=f"{query.message.text}\n\n🔓 <b>ההודעה שוחררה כהודעה לגיטימית. מעבד כעת ב-AI...</b>",
            parse_mode="HTML",
        )

        chat_id = spam_data["chat_id"]
        user_text = spam_data["user_text"]
        user_id = spam_data["user_id"]
        user_name = spam_data["user_name"]

        conv = conversation_manager.get_or_create(chat_id=chat_id, user_id=user_id, user_name=user_name)

        try:
            result_json = gemini_service.analyze_and_draft(conv, user_text)
        except Exception as e:
            logger.error(f"Error analyzing unmarket spam: {e}")
            await safe_send_message(context=context, chat_id=config.ADMIN_CHAT_ID, text=f"⚠️ שגיאה בעיבוד: {e}")
            return

        draft = result_json.get("draft_reply", "שלום, קיבלנו את פנייתך.")
        entities = result_json.get("entities_extracted", {})
        sentiment = result_json.get("customer_sentiment", "SATISFIED_OR_NEUTRAL")
        deal_closed = bool(result_json.get("deal_closed", False))
        deal_summary = result_json.get("deal_summary", "")

        conv.update_deal(entities)

        image_info = image_service.get_event_images(
            event_type=entities.get("event_type"),
            user_text=user_text,
            similar_events=result_json.get("similar_historical_events", []),
        )

        pending_approvals[req_key] = {
            "chat_id": chat_id,
            "reply_to_message_id": spam_data["reply_to_message_id"],
            "draft_reply": draft,
            "user_text": user_text,
            "entities": entities,
            "deal_closed": deal_closed,
            "deal_summary": deal_summary,
            "sentiment": sentiment,
            "image_info": image_info,
        }

        await send_admin_card(context, req_key, conv, admin_user, user_text, result_json, image_info=image_info)
        return

    elif action == "confirm_spam":
        spam_data = pending_spam.pop(req_key, None)
        if not spam_data:
            await query.edit_message_text("פניית ספאם זו כבר טופלה.")
            return

        await safe_send_message(
            context=context,
            chat_id=spam_data["chat_id"],
            reply_to_message_id=spam_data["reply_to_message_id"],
            text=spam_data["spam_msg"],
        )
        await safe_edit_message_text(
            query=query,
            text=f"{query.message.text}\n\n🚫 <b>הספאם אושר ונשלחה אזהרה ללקוח.</b>",
            parse_mode="HTML",
        )
        return

    elif action == "dismiss_spam":
        pending_spam.pop(req_key, None)
        await safe_edit_message_text(
            query=query,
            text=f"{query.message.text}\n\n🗑️ <b>פניית הספאם נמחקה ללא שליחת תגובה.</b>",
            parse_mode="HTML",
        )
        return

    # -------------------------------------------------------------
    # טיפול בטיוטות רגילות ועריכתן
    # -------------------------------------------------------------
    req_data = pending_approvals.get(req_key)
    if not req_data:
        await query.edit_message_text("פנייה זו כבר טופלה או פג תוקפה.")
        return

    chat_id = req_data["chat_id"]
    reply_to_msg_id = req_data["reply_to_message_id"]
    conv = conversation_manager.get_conversation(chat_id)

    # 1. מצב עריכת טיוטה
    if action == "edit_draft":
        if admin_user:
            awaiting_draft_edit[admin_user.id] = req_key
        await safe_edit_message_text(
            query=query,
            text=f"{query.message.text}\n\n✏️ <b>מצב עריכה הופעל!</b>\nשלח כעת הודעה חדשה בצ'אט עם נוסח הטיוטה שתרצה לשלוח ללקוח.",
            parse_mode="HTML",
        )
        return

    # 2. אישור שליחת טיוטה + תמונות המחשה
    elif action == "approve_photos":
        image_info = req_data.get("image_info")
        img_paths = image_info.get("image_paths", []) if image_info else []

        await safe_send_message(
            context=context,
            chat_id=chat_id,
            reply_to_message_id=reply_to_msg_id,
            text=req_data["draft_reply"],
        )

        if img_paths:
            concept_title = image_info.get("title", "אירוע לדוגמה")
            caption = f"📸 <b>להמחשה מאירועים דומים שלנו: {concept_title}</b>"
            await safe_send_media_group(
                context=context,
                chat_id=chat_id,
                image_paths=img_paths,
                caption=caption,
                reply_to_message_id=reply_to_msg_id,
            )

        if conv:
            conv.add_message("user", req_data["user_text"])
            conv.add_message("assistant", req_data["draft_reply"])
            conv.add_message("assistant", f"[נשלחו 2 תמונות המחשה מקונספט: {image_info.get('title', '') if image_info else ''}]")

        del pending_approvals[req_key]
        await safe_edit_message_text(
            query=query,
            text=f"{query.message.text}\n\n✅ <b>הטיוטה ו-2 תמונות ההמחשה נשלחו בהצלחה ללקוח! 🖼️</b>",
            parse_mode="HTML",
        )

    # 3. אישור שליחת טיוטה (טקסט בלבד)
    elif action == "approve":
        await safe_send_message(
            context=context,
            chat_id=chat_id,
            reply_to_message_id=reply_to_msg_id,
            text=req_data["draft_reply"],
        )
        if conv:
            conv.add_message("user", req_data["user_text"])
            conv.add_message("assistant", req_data["draft_reply"])

        if req_data.get("deal_closed"):
            d = conv.deal_details if conv else req_data.get("entities", {})
            date = d.get("date") or req_data.get("entities", {}).get("timeline") or "תאריך בתיאום"
            ev_type = d.get("event_type") or "אירוע"
            guests = d.get("guest_count") or 0
            price = d.get("price") or 0
            schedule_manager.book_new_event(
                date=str(date),
                event_type=str(ev_type),
                guest_count=int(guests) if str(guests).isdigit() else 0,
                price=float(price) if str(price).replace('.', '', 1).isdigit() else 0.0,
                title=f"אירוע {ev_type} - {conv.user_name if conv else 'לקוח'}",
            )
            conversation_manager.end_conversation(chat_id, reason="DEAL_CLOSED")

        del pending_approvals[req_key]
        await safe_edit_message_text(
            query=query,
            text=f"{query.message.text}\n\n✅ <b>הטיוטה אושרה ונשלחה בהצלחה ללקוח!</b>",
            parse_mode="HTML",
        )

    # 4. דחיית הטיוטה
    elif action == "reject":
        del pending_approvals[req_key]
        await safe_edit_message_text(
            query=query,
            text=f"{query.message.text}\n\n❌ <b>הטיוטה נדחתה ולא נשלחה.</b>",
            parse_mode="HTML",
        )

    # 5. שיתוף מספר טלפון לשיחה ישירה
    elif action == "share_phone":
        phone_msg = (
            f"נשמח לתת לך מענה אישי ומיידי! 📞\n"
            f"ניתן ליצור קשר ישירות בטלפון או בווטסאפ: {config.COMPANY_PHONE}\n"
            f"נציג אישי ישמח לענות ולסייע בכל שאלה."
        )
        await safe_send_message(
            context=context,
            chat_id=chat_id,
            reply_to_message_id=reply_to_msg_id,
            text=phone_msg,
        )
        if conv:
            conv.phone_shared = True
            conv.add_message("user", req_data["user_text"])
            conv.add_message("assistant", phone_msg)

        del pending_approvals[req_key]
        await safe_edit_message_text(
            query=query,
            text=f"{query.message.text}\n\n📞 <b>פרטי הטלפון שותפו בהצלחה עם הלקוח!</b>",
            parse_mode="HTML",
        )

    # 6. סגירת עסקה, שריון ביומן והעברה למפיק
    elif action == "close_deal":
        d = conv.deal_details if conv else req_data.get("entities", {})
        date = d.get("date") or req_data.get("entities", {}).get("timeline") or "תאריך בתיאום"
        ev_type = d.get("event_type") or "אירוע"
        guests = d.get("guest_count") or 0
        price = d.get("price") or 0

        # סגירת התאריך ביומן החברה
        schedule_manager.book_new_event(
            date=str(date),
            event_type=str(ev_type),
            guest_count=int(guests) if str(guests).isdigit() else 0,
            price=float(price) if str(price).replace('.', '', 1).isdigit() else 0.0,
            title=f"אירוע {ev_type} - {conv.user_name if conv else 'לקוח'}",
        )

        closing_msg = (
            f"🎉 <b>איזה כיף, סגרנו!</b>\n\n"
            f"סגרנו ושריינו עבורך את התאריך בלוח השנה שלנו:\n"
            f"📅 <b>תאריך משוריין:</b> {date}\n"
            f"🏷 <b>סוג אירוע:</b> {ev_type}\n"
            f"👥 <b>כמות מוזמנים:</b> {guests}\n\n"
            f"המפיק שלנו ייצור איתך קשר בהקדם כדי להמשיך ישירות בתכנון המפורט והפקת האירוע. תודה רבה ושיהיה המון מזל טוב! 🌟"
        )

        await safe_send_message(
            context=context,
            chat_id=chat_id,
            reply_to_message_id=reply_to_msg_id,
            text=closing_msg,
        )

        conversation_manager.end_conversation(chat_id, reason="DEAL_CLOSED")
        del pending_approvals[req_key]

        await safe_edit_message_text(
            query=query,
            text=f"{query.message.text}\n\n🎉 <b>העסקה נסגרה בהצלחה! התאריך נסגר ביומן (company_schedule.json) ונשלחה הודעה ללקוח שהמפיק ימשיך מולו.</b>",
            parse_mode="HTML",
        )


def main():
    app = ApplicationBuilder().token(config.TELEGRAM_TOKEN).build()
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_incoming_message)
    )
    app.add_handler(CallbackQueryHandler(handle_admin_callback))

    print("🚀 סוכן EventTriage מחובר ופועל בהצלחה!")
    print(f"📡 מאזין לצ'אט לידים ({config.LEADS_CHAT_ID}) ולצ'אט בקרה ({config.ADMIN_CHAT_ID})")
    app.run_polling()


if __name__ == "__main__":
    main()
