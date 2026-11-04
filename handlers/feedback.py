"""بازخورد: کاربر می‌نویسد → مدیریت می‌بیند → جواب مستقیم به کاربر می‌رسد."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import config
import database as db
from keyboards import main_menu_kb
from utils import helpers as H

log = logging.getLogger("bagoodit.feedback")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      user: dict) -> None:
    uid = user["telegram_id"]
    text = (update.message.text or "").strip()
    if len(text) > config.FEEDBACK_MAX_LEN:
        await update.message.reply_text(
            f"پیام خیلی طولانی است؛ حداکثر {config.FEEDBACK_MAX_LEN} کاراکتر.")
        return
    fb_id = db.add_feedback(uid, text)
    db.set_state(uid, config.ST_MAIN)
    await update.message.reply_text(
        "✅ <b>پیامت برای مدیریت بگودیت ارسال شد.</b>\nجواب همین‌جا به تو اعلام می‌شود.",
        parse_mode="HTML", reply_markup=main_menu_kb())
    if config.ADMIN_ID:
        sender = db.get_user(uid)
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("💬 پاسخ به این پیام", callback_data=f"fb:reply:{fb_id}")]])
        await H.notify(
            context.bot, config.ADMIN_ID,
            f"📝 <b>بازخورد جدید #{fb_id}</b>\n"
            f"از: {H.esc(sender['nickname'] or '—')} "
            f"(<code>{H.esc(sender['bot_user_id'] or uid)}</code>)\n\n"
            f"{H.esc(text[:800])}", reply_markup=kb)


async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict) -> None:
    q = update.callback_query
    data = q.data or ""
    # فقط ادمین حق پاسخ دارد
    if q.from_user.id != config.ADMIN_ID:
        await q.answer("فقط مدیریت!")
        return
    parts = data.split(":")
    if parts[1] == "reply" and parts[2].isdigit():
        fid = int(parts[2])
        fb = db.get_feedback(fid)
        if not fb:
            await q.answer("یافت نشد!")
            return
        db.set_state(q.from_user.id, config.ST_ADMIN_FB, {"fb_id": fid})
        await q.answer()
        await q.message.reply_text(
            f"💬 متن پاسخ برای بازخورد #{fid} را بنویس (این پیام مستقیم به کاربر می‌رسد):")
        return
    await q.answer()
