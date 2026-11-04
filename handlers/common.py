"""روتر اصلی پیام‌ها و callbackها + کنترل نرخ + مدیریت خطای سراسری."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import config
import database as db
from utils import helpers as H
from utils.helpers import rate_limiter

log = logging.getLogger("bagoodit")

_admin_error_ts = [0.0]


def _banned_text() -> str:
    return ("🚫 <b>دسترسی شما مسدود شده است.</b>\n"
            "اگر فکر می‌کنی اشتباهی رخ داده، از طریق پشتیبانی پیام بده.")


async def _touch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
    """ایجاد/به‌روزرسانی کاربر + کنترل نرخ. None یعنی پیام را نادیده بگیر."""
    uid = update.effective_user.id
    user = db.ensure_user(uid)
    db.update_user(uid, state=user["state"])  # last_active را تازه می‌کند
    if user["banned"]:
        if update.message:
            await update.message.reply_text(_banned_text(), parse_mode="HTML")
        elif update.callback_query:
            await update.callback_query.answer(_banned_text(), show_alert=True)
        return None
    if not rate_limiter.allow(uid):
        return None
    return user


# ---------------- دستورات ----------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _touch(update, context)
    if user is None:
        return
    from handlers import registration
    await registration.start(update, context, user, context.args or [])


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _touch(update, context)
    if user is None:
        return
    from services import matching as mh
    from keyboards import main_menu_kb
    uid = update.effective_user.id
    state = user["state"]
    if state == config.ST_SEARCHING:
        await mh.cancel_search(context, uid)
        return
    if state in (config.ST_CHAT,):
        from handlers import chat as ch
        await ch.leave_chat(update, context, user, notify_partner=True)
        return
    db.set_state(uid, config.ST_MAIN)
    await update.message.reply_text("✅ به منوی اصلی برگشتی.",
                                    reply_markup=main_menu_kb())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _touch(update, context)
    if user is None:
        return
    from handlers import main_menu
    await main_menu.send_help(update, context)


# ---------------- روتر پیام متنی ----------------
async def route_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _touch(update, context)
    if user is None:
        return
    uid = update.effective_user.id
    state = user["state"]

    if state == config.ST_NONE:
        await update.message.reply_text("👋 برای شروع، دستور /start را بزن.")
        return

    # حالت‌های ثبت‌نام
    if state in (config.ST_REG_AGE, config.ST_REG_NICKNAME, config.ST_REG_GENDER,
                 config.ST_REG_PROVINCE, config.ST_REG_CITY, config.ST_REG_PHOTO):
        from handlers import registration
        await registration.handle_text(update, context, user)
        return

    # منوی اصلی
    if state == config.ST_MAIN:
        from handlers import main_menu
        await main_menu.handle_text(update, context, user)
        return

    # منوی تطبیق
    if state == config.ST_MATCH_MENU:
        from handlers import matching
        await matching.handle_text(update, context, user)
        return

    # صف انتظار
    if state == config.ST_SEARCHING:
        from handlers import matching
        await matching.handle_searching_text(update, context, user)
        return

    # ویزارد جست‌وجوی پیشرفته
    if state == config.ST_FILTER:
        from handlers import matching
        await matching.handle_filter_text(update, context, user)
        return

    # درون چت
    if state == config.ST_CHAT:
        from handlers import chat
        await chat.handle_message(update, context, user)
        return

    # بازخورد
    if state == config.ST_FEEDBACK:
        from handlers import feedback
        await feedback.handle_text(update, context, user)
        return

    # جست‌وجوی کاربر با شناسه
    if state == config.ST_SEARCH_USER:
        from handlers import search_user
        await search_user.handle_input(update, context, user)
        return

    # حالت‌های ادمین
    if state in (config.ST_ADMIN_FIND, config.ST_ADMIN_COIN, config.ST_ADMIN_MSG,
                 config.ST_ADMIN_FB, config.ST_ADMIN_BC, config.ST_ADMIN_SET):
        from handlers import admin
        await admin.handle_text(update, context, user)
        return

    # حالت ناشناخته → منوی اصلی
    db.set_state(uid, config.ST_MAIN)
    from keyboards import main_menu_kb
    await update.message.reply_text("به منوی اصلی برگشتی.", reply_markup=main_menu_kb())


# ---------------- روتر رسانه ----------------
async def route_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _touch(update, context)
    if user is None:
        return
    state = user["state"]

    if state == config.ST_REG_PHOTO:
        from handlers import registration
        await registration.handle_photo(update, context, user)
        return

    if state == config.ST_CHAT:
        from handlers import chat
        await chat.handle_message(update, context, user)
        return

    if state == config.ST_NONE:
        await update.message.reply_text("👋 برای شروع، دستور /start را بزن.")
        return

    await update.message.reply_text("فقط عکس را در مرحله‌ی ثبت عکس پروفایل بفرست یا "
                                    "برای ادامه از منو استفاده کن.")


# ---------------- روتر callback ----------------
async def cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    data = q.data or ""
    user = await _touch(update, context)
    if user is None:
        return

    try:
        if data == "noop" or data.endswith(":noop"):
            await q.answer()
            return

        if data.startswith("reg:"):
            from handlers import registration
            await registration.on_cb(update, context, user)
            return

        if data.startswith("fw:"):
            from handlers import matching
            await matching.on_cb(update, context, user)
            return

        if data.startswith("pf:") or data.startswith("coins:"):
            from handlers import main_menu
            await main_menu.on_cb(update, context, user)
            return

        if data.startswith("chat:") or data.startswith("rpt:"):
            from handlers import chat
            await chat.on_cb(update, context, user)
            return

        if data.startswith("crq:") or data.startswith("usr:"):
            from handlers import search_user
            await search_user.on_cb(update, context, user)
            return

        if data.startswith("fb:"):
            from handlers import feedback
            await feedback.on_cb(update, context, user)
            return

        if data.startswith("adm:"):
            from handlers import admin
            await admin.on_cb(update, context, user)
            return

        await q.answer()
    except Exception:
        # خطای هندلرهای اختصاصی به error_handler پاس داده نمی‌شود چون خودش است؛
        # پس اینجا لاگ می‌کنیم و پاسخ خاموش می‌دهیم.
        log.exception("callback error: %s", data)
        try:
            await q.answer("⚠️ خطایی رخ داد؛ دوباره تلاش کن.")
        except Exception:
            pass


# ---------------- مدیریت خطای سراسری ----------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled exception", exc_info=context.error)
    import time as _time
    now = _time.monotonic()
    if now - _admin_error_ts[0] > 300 and config.ADMIN_ID:  # حداکثر هر ۵ دقیقه
        _admin_error_ts[0] = now
        try:
            err = str(context.error)[:300]
            await context.bot.send_message(
                chat_id=config.ADMIN_ID,
                text=f"⚠️ خطای سرور بگودیت:\n<code>{H.esc(err)}</code>",
                parse_mode="HTML")
        except Exception:
            pass
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ خطایی پیش آمد؛ دوباره تلاش کن.")
    except Exception:
        pass
