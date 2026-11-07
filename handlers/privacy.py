"""منوی «🔐 حریم خصوصی» — تنظیمات واقعی با اثر مستقیم در رفتار بگودیت.

هر گزینه در ستون privacy جدول users ذخیره می‌شود و در این نقاط اعمال می‌شود:
• show_online    → کارتِ پروفایل برای «دیگران» (وضعیت مخفی/نمایش)
• show_city      → کارتِ پروفایل برای «دیگران» (شهر مخفی/نمایش)
• discoverable   → جست‌وجوی کاربر با شناسه‌ی ناشناس
• allow_requests → دکمه‌ی «درخواست چت» در جست‌وجوی کاربر
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
import database as db

log = logging.getLogger("bagoodit.privacy")

PRIVACY_TEXT = (
    "🔐 <b>حریم خصوصی</b>\n\n"
    "این تنظیم‌ها بلافاصله و به‌صورت واقعی اعمال می‌شوند:\n\n"
    "• <b>وضعیت آنلاین</b> — اگر خاموش باشد، دیگران در پروفایلت «🌙 مخفی» می‌بینند.\n"
    "• <b>نمایش شهر</b> — اگر خاموش باشد، شهرت به دیگران نشان داده نمی‌شود.\n"
    "• <b>قابل پیدا شدن با شناسه</b> — اگر خاموش باشد، کسی با شناسه‌ی ناشناست "
    "پیدا‌ت نمی‌کند.\n"
    "• <b>پذیرش درخواست چت</b> — اگر خاموش باشد، درخواست چت به‌ت نمی‌رسد.\n\n"
    "⚠️ این تنظیمات روی چت‌های در حال جریان اثری ندارند؛ فقط جست‌وجو و کارت پروفایل را کنترل می‌کنند."
)


def _toggle_label(flag_on: bool) -> str:
    return "✅ روشن" if flag_on else "❌ خاموش"


def privacy_kb(uid: int) -> InlineKeyboardMarkup:
    pr = db.get_privacy(uid)
    rows = []
    for key, label in db.PRIVACY_LABELS.items():
        on = pr.get(key) == "1"
        rows.append([InlineKeyboardButton(
            f"{'🟢' if on else '⚪️'} {label}: {_toggle_label(on)}",
            callback_data=f"prv:toggle:{key}")])
    rows.append([InlineKeyboardButton("🔄 تازه‌سازی", callback_data="prv:view")])
    rows.append([InlineKeyboardButton("⬅️ منوی اصلی", callback_data="prv:back")])
    return InlineKeyboardMarkup(rows)


async def show_privacy(q, uid: int) -> None:
    await q.message.reply_text(PRIVACY_TEXT, parse_mode="HTML",
                               reply_markup=privacy_kb(uid))


async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE,
                user: dict) -> None:
    q = update.callback_query
    data = q.data or ""
    uid = user["telegram_id"]
    parts = data.split(":")

    if data == "prv:view":
        await q.answer()
        await show_privacy(q, uid)
        return

    if data == "prv:back":
        from keyboards import main_menu_kb
        db.set_state(uid, config.ST_MAIN)
        await q.answer()
        await q.message.reply_text("منوی اصلی:", reply_markup=main_menu_kb())
        return

    if len(parts) == 3 and parts[0] == "prv" and parts[1] == "toggle":
        key = parts[2]
        if key not in db.PRIVACY_DEFAULTS:
            await q.answer("گزینه‌ی نامعتبر!")
            return
        pr = db.get_privacy(uid)
        new_val = "0" if pr.get(key) == "1" else "1"
        db.set_privacy_flag(uid, key, new_val)
        await q.answer("ثبت شد ✅")
        await show_privacy(q, uid)
        return

    await q.answer()
