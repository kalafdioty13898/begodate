"""چت ناشناس: انتقال پیام‌ها، پروفایل طرف، پایان چت، گزارش، پاسخ‌های کاربر تستی.
قوانین این ماژول:
• ۵ دقیقه اول هر چت فقط فارسی (تشخیص واقعی یونیکد؛ زمان شروع از دیتابیس — پایدار در Restart)
• پیام‌ها به‌صورت محدود برای رسیدگی به گزارش‌ها ذخیره می‌شوند (حداکثر ۳۰ روز)
• پایان چت تأیید دوم دارد؛ خروج و گزارش همیشه در دسترس‌اند"""
import logging
import random
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
import database as db
from keyboards import (BTN_CHAT_END, BTN_CHAT_PROFILE, BTN_CHAT_REPORT,
                       BTN_SKIP_PHOTO, chat_kb, main_menu_kb, report_reasons_kb)
from services import auto_reply
from services import settings as S
from utils import helpers as H
from utils import validators as V

log = logging.getLogger("bagoodit.chat")

LATIN_BLOCK_ERROR = ("❌ در پنج دقیقه اول چت، فقط می‌توانید به زبان فارسی "
                     "پیام ارسال کنید.")
LANG_WINDOW_SECONDS = 300  # ۵ دقیقه


def _chat_age_seconds(chat: dict) -> float:
    """عمر چت بر اساس زمان شروع ثبت‌شده در دیتابیس (برای هر دو طرف یکسان)."""
    try:
        started = datetime.fromisoformat(chat["started_at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - started).total_seconds()
    except (ValueError, TypeError):
        return 1e9  # خطای تجزیه → محدودیت اعمال نمی‌شود تا کاربر گیر نکند


def _msg_kind(msg) -> str:
    if msg.text:
        return "text"
    if msg.photo:
        return "photo"
    if msg.video:
        return "video"
    if msg.video_note:
        return "video_note"
    if msg.voice:
        return "voice"
    if msg.audio:
        return "audio"
    if msg.sticker:
        return "sticker"
    if msg.animation:
        return "animation"
    if msg.document:
        return "document"
    if msg.contact:
        return "contact"
    if msg.location:
        return "location"
    return "other"


# ---------------- پیام‌های داخل چت ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         user: dict) -> None:
    uid = user["telegram_id"]
    msg = update.effective_message
    chat = db.get_active_chat(uid)
    if not chat:
        db.set_state(uid, config.ST_MAIN)
        await msg.reply_text("این چت تمام شده است.", reply_markup=main_menu_kb())
        return

    pid = db.partner_id_of(chat, uid)
    partner = db.get_user(pid)
    if not partner:
        await _close_and_notify(update, context, chat, uid,
                                "❌ طرف مقابل در دسترس نیست؛ چت بسته شد.")
        return

    # --- قانون زبان: ۵ دقیقه اول چت فقط فارسی (پیام به طرف مقابل نمی‌رود) ---
    content = msg.text or msg.caption or ""
    if content and _chat_age_seconds(chat) < LANG_WINDOW_SECONDS \
            and V.has_latin(content):
        await msg.reply_text(LATIN_BLOCK_ERROR)
        return

    # شریک تستی → پاسخ خودکار (پیام کاربر تستی هرگز وارد این موتور نمی‌شود)
    if partner["is_test_user"]:
        if msg.text and msg.text in (BTN_CHAT_PROFILE, BTN_CHAT_END, BTN_CHAT_REPORT,
                                     BTN_SKIP_PHOTO):
            await _handle_chat_buttons(update, context, user, chat, pid, msg.text)
            return
        used = chat["test_replies_used"]
        cap = chat["test_replies_max"] or S.get_int("test_user_max_replies")
        if used >= cap:
            await _cap_close(update, context, chat, uid)
            return
        db.add_chat_message(chat["chat_id"], uid, _msg_kind(msg),
                            _stored_body(msg), msg.message_id)
        db.bump_test_reply(chat["chat_id"])
        category = auto_reply.detect_intent(msg.text) if msg.text else "short"
        delay = random.uniform(S.get_float("test_reply_min_delay"),
                               S.get_float("test_reply_max_delay"))
        context.job_queue.run_once(
            auto_reply.reply_job, when=delay,
            data={"chat_id": chat["chat_id"], "test_uid": pid, "real_uid": uid,
                  "category": category},
            name=f"trep:{chat['chat_id']}:{used + 1}")
        return

    # شریک واقعی → انتقال پیام
    if msg.text and msg.text in (BTN_CHAT_PROFILE, BTN_CHAT_END, BTN_CHAT_REPORT,
                                 BTN_SKIP_PHOTO):
        await _handle_chat_buttons(update, context, user, chat, pid, msg.text)
        return

    db.add_chat_message(chat["chat_id"], uid, _msg_kind(msg),
                        _stored_body(msg), msg.message_id)
    try:
        await context.bot.copy_message(chat_id=pid, from_chat_id=uid,
                                       message_id=msg.message_id)
    except Exception as e:
        name = type(e).__name__
        if name == "Forbidden":
            await _close_and_notify(update, context, chat, uid,
                                    "❌ طرف مقابل ربات را بلاک کرده؛ چت بسته شد.")
        else:
            await msg.reply_text("⚠️ ارسال پیام ناموفق بود؛ دوباره تلاش کن.")
        return


def _stored_body(msg) -> str | None:
    """متن پیام یا کپشن (تا ۵۰۰ کاراکتر) برای بررسی گزارش؛ محتوای رسانه ذخیره نمی‌شود."""
    body = msg.text or msg.caption
    if not body:
        return None
    return body[:500]


async def _handle_chat_buttons(update, context, user, chat, pid, text) -> None:
    if text == BTN_CHAT_PROFILE:
        await send_partner_profile(update, context, pid)
        return
    if text == BTN_CHAT_END:
        # تأیید دوم برای جلوگیری از لمس اشتباهی؛ خروج همیشه ممکن است
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ بله، پایان چت", callback_data="chat:endok"),
            InlineKeyboardButton("❌ نه، ادامه می‌دهیم", callback_data="chat:endno")]])
        await update.effective_message.reply_text(
            "🔴 <b>مطمئنی که می‌خواهی چت را پایان بدهی؟</b>",
            parse_mode="HTML", reply_markup=kb)
        return
    if text == BTN_CHAT_REPORT:
        await update.effective_message.reply_text(
            "⚠️ دلیل گزارش را انتخاب کن:", reply_markup=report_reasons_kb())
        return


async def send_partner_profile(update, context, pid: int) -> None:
    partner = db.get_user(pid)
    if not partner:
        await update.effective_message.reply_text("پروفایل در دسترس نیست.")
        return
    card = H.user_card(partner)
    if partner["avatar_file_id"]:
        try:
            await context.bot.send_photo(chat_id=update.effective_chat.id,
                                         photo=partner["avatar_file_id"],
                                         caption=card, parse_mode="HTML")
            return
        except Exception:
            pass
    await update.effective_message.reply_text(card, parse_mode="HTML")


# ---------------- پایان چت ----------------
async def leave_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict,
                     notify_partner=True) -> None:
    uid = user["telegram_id"]
    chat = db.get_active_chat(uid)
    if not chat:
        await update.effective_message.reply_text("چتی فعال نیست.",
                                                  reply_markup=main_menu_kb())
        return
    pid = db.partner_id_of(chat, uid)
    db.close_chat(chat["chat_id"], closer_id=uid)
    await update.effective_message.reply_text(
        "🔚 <b>چت پایان یافت.</b>\nامیدواریم لحظات خوبی داشته باشی.",
        parse_mode="HTML", reply_markup=main_menu_kb())
    if notify_partner and not (await _partner_is_test(pid)):
        from utils import helpers as H
        await H.notify(context.bot, pid,
                       "❌ <b>طرف مقابل چت را پایان داد.</b>\nمی‌توانی دوباره جست‌وجو کنی.",
                       reply_markup=main_menu_kb())


async def _partner_is_test(pid: int) -> bool:
    p = db.get_user(pid)
    return bool(p and p["is_test_user"])


async def _close_and_notify(update, context, chat, uid: int, text: str) -> None:
    db.close_chat(chat["chat_id"], closer_id=None)
    from utils import helpers as H
    await H.notify(context.bot, uid, text, reply_markup=main_menu_kb())


async def _cap_close(update, context, chat, uid: int) -> None:
    db.close_chat(chat["chat_id"], closer_id=None)
    from utils import helpers as H
    await H.notify(
        context.bot, uid,
        "🧪 <b>این حساب تستی به سقف تعداد پیام‌های چت رسید.</b>\nچت بسته شد؛ "
        "می‌توانی دوباره جست‌وجو کنی.", reply_markup=main_menu_kb())


# ---------------- callbackها: پایان چت و گزارش ----------------
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict) -> None:
    q = update.callback_query
    data = q.data or ""
    uid = user["telegram_id"]

    if data == "chat:endok":
        await q.answer()
        await leave_chat(update, context, user, notify_partner=True)
        return

    if data == "chat:endno":
        await q.answer("ادامه می‌دهیم 🙂")
        return

    if data.startswith("rpt:"):
        part = data.split(":")[1]
        if part == "cancel":
            await q.answer()
            await q.message.reply_text("گزارش لغو شد.", reply_markup=chat_kb())
            return
        idx = int(part) if part.isdigit() else None
        if idx is None or not (0 <= idx < len(config.REPORT_REASONS)):
            await q.answer("نامعتبر!")
            return
        chat = db.get_active_chat(uid)
        if not chat:
            await q.answer("چت فعال نیست.")
            return
        pid = db.partner_id_of(chat, uid)
        reason = config.REPORT_REASONS[idx]
        rid = db.add_report(uid, pid, chat["chat_id"], reason)
        await q.answer("گزارش ثبت شد ✅")
        await q.message.reply_text(
            "✅ <b>گزارش تو ثبت شد.</b>\nتیم بگودیت بررسی می‌کند و در صورت تخلف، "
            "کاربر متخلف مسدود می‌شود.", parse_mode="HTML", reply_markup=chat_kb())
        # اطلاع فوری به ادمین با دکمه‌های سریع (مشاهده جرم + بن + بستن پرونده)
        if config.ADMIN_ID:
            reporter = db.get_user(uid)
            reported = db.get_user(pid)
            from telegram import InlineKeyboardButton as _IKB, InlineKeyboardMarkup as _IKM
            kb = _IKM([
                [_IKB("👁 مشاهده جرم", callback_data=f"adm:crime:{rid}"),
                 _IKB("🚫 مسدودسازی متخلف", callback_data=f"adm:rban:{pid}:{rid}")],
                [_IKB("✅ بستن پرونده", callback_data=f"adm:rdone:{rid}")]])
            await H.notify(
                context.bot, config.ADMIN_ID,
                f"⚠️ <b>گزارش جدید #{rid}</b>\n"
                f"از: <code>{H.esc(reporter['bot_user_id'] or uid)}</code>\n"
                f"علیه: <code>{H.esc(reported['bot_user_id'] or pid)}</code>\n"
                f"دلیل: {H.esc(reason)}\n"
                f"چت: #{chat['chat_id']}",
                reply_markup=kb)
        return

    await q.answer()
