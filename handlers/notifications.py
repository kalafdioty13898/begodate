"""مرکز اعلان‌ها — لیست اینلاین، صفحه‌بندی، خواندن تک‌تک، اجرای action هر اعلان.

امنیت: هر callback با user_id در دیتابیس سنجیده می‌شود؛ اعلانِ کاربر دیگر
با هیچ callback_data جعلی قابل مشاهده یا خواندن نیست (چک در سطح SQL).
"""
import json
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
import database as db
from services import notifications as N
from utils import helpers as H
from utils import jalali as J

log = logging.getLogger("bagoodit.notifcenter")

FORGE_ALERT = "⛔ این اعلان متعلق به تو نیست!"


def _short_title(title: str, limit: int = None) -> str:
    limit = limit or config.NOTIF_BUTTON_TITLE_MAX
    t = (title or "").strip()
    return t if len(t) <= limit else t[:limit - 1] + "…"


def _notif_button(n: dict) -> InlineKeyboardButton:
    """دکمه‌ی مستقل هر اعلان با تاریخ/ساعت جلالی — طبق مشخصات مأموریت."""
    mark = "🔴" if not n["is_read"] else "✅"
    icon = N.icon_of(n["type"])
    when = J.fmt_jdatetime(n["created_at"])
    return InlineKeyboardButton(
        f"{mark} {icon} {_short_title(n['title'])} | 🕐 {when}",
        callback_data=f"nc:view:{n['id']}")


def _center_kb(uid: int, page: int) -> InlineKeyboardMarkup:
    total = db.notif_count(uid)
    pages = max(1, (total + config.NOTIF_PAGE_SIZE - 1) // config.NOTIF_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    rows = db.list_notifications(uid, limit=config.NOTIF_PAGE_SIZE,
                                 offset=page * config.NOTIF_PAGE_SIZE)
    kb = [[_notif_button(n)] for n in rows]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("➡️ قبلی", callback_data=f"nc:page:{page - 1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(f"📄 {page + 1}/{pages}", callback_data="nc:noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("⬅️ بعدی", callback_data=f"nc:page:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("✅ خواندن همه", callback_data="nc:readall")])
    kb.append([InlineKeyboardButton("🔄 تازه‌سازی", callback_data=f"nc:open:{page}"),
               InlineKeyboardButton("⬅️ منوی اصلی", callback_data="nc:back")])
    return InlineKeyboardMarkup(kb)


async def _show_center(q, uid: int, page: int = 0) -> None:
    total = db.notif_count(uid)
    unread = db.unread_count(uid)
    if total == 0:
        text = ("🔔 <b>مرکز اعلان‌ها</b>\n\n"
                "فعلاً اعلانی نداری 🌙\n"
                "از این به بعد هر رویداد مهم (درخواست چت، پاداش سکه، پاسخ پشتیبانی و…) "
                "اینجا جمع می‌شود و هر شب اگر اعلان خوانده‌نشده داشته باشی بهت خبر می‌دهیم.")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 تازه‌سازی", callback_data="nc:open:0"),
                                    InlineKeyboardButton("⬅️ منوی اصلی", callback_data="nc:back")]])
    else:
        text = (f"🔔 <b>مرکز اعلان‌ها</b>\n\n"
                f"🔴 خوانده‌نشده: <b>{unread}</b> | 📋 کل: <b>{total}</b>\n"
                "روی هر اعلان بزن تا باز شود:")
        kb = _center_kb(uid, page)
    await q.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


ACTION_LABELS = {
    "sender_profile": "🔍 پروفایل فرستنده",
    "balance": "🪙 مشاهده موجودی",
    "referral": "🎁 لینک دعوت من",
    "feedback": "💬 پاسخ به مدیریت",
    "profile": "👤 پروفایل من",
}


def _view_text(n: dict) -> str:
    status = "✅ خوانده شد" if n["is_read"] else "🔴 خوانده‌نشده"
    return (f"{N.icon_of(n['type'])} <b>{H.esc(n['title'])}</b>\n\n"
            f"{H.esc(n['message'])}\n\n"
            f"🕐 {J.fmt_jdatetime(n['created_at'])} | {N.label_of(n['type'])}\n"
            f"وضعیت: {status}")


async def _do_action(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     uid: int, n: dict) -> None:
    """اجرای action اختصاصی هر نوع اعلان — همه‌ی actionها واقعی‌اند."""
    act = n["action_type"]
    try:
        meta = json.loads(n["metadata"] or "{}")
    except (ValueError, TypeError):
        meta = {}
    if act == "balance":
        bal = db.get_balance(uid)
        await update.effective_message.reply_text(
            f"🪙 <b>موجودی فعلی سکه‌های تو: {bal}</b>", parse_mode="HTML")
        return
    if act == "referral":
        username = config.BOT_USERNAME or "this_bot"
        cnt = db.referral_count(uid)
        link = f"https://t.me/{username}?start=ref{uid}"
        await update.effective_message.reply_text(
            f"🎁 <b>لینک اختصاصی دعوت تو:</b>\n<code>{H.esc(link)}</code>\n\n"
            f"دعوت‌های موفق تا کنون: {cnt}", parse_mode="HTML")
        return
    if act == "feedback":
        db.set_state(uid, config.ST_FEEDBACK, {})
        await update.effective_message.reply_text(
            "📝 پیامت را بنویس؛ مستقیم برای مدیریت فرستاده می‌شود.\nبرای لغو: /cancel",
            reply_markup=_remove_kb())
        return
    if act == "profile":
        from handlers import main_menu
        await main_menu.show_profile(update, context, uid)
        return
    if act == "sender_profile":
        bot_id = (meta or {}).get("bot_id")
        target = db.get_user_by_bot_id(bot_id) if bot_id else None
        if not target or target["banned"]:
            await update.effective_message.reply_text("❌ این کاربر دیگر در دسترس نیست.")
            return
        card = H.user_card(target, show_contact_hint=True)
        from telegram import InlineKeyboardMarkup as _IKM
        from telegram import InlineKeyboardButton as _IKB
        kb = _IKM([[ _IKB("💬 درخواست چت", callback_data=f"usr:req:{target['telegram_id']}")]])
        if target["avatar_file_id"]:
            try:
                await context.bot.send_photo(chat_id=uid, photo=target["avatar_file_id"],
                                             caption=card, parse_mode="HTML",
                                             reply_markup=kb)
                return
            except Exception:
                pass
        await update.effective_message.reply_text(card, parse_mode="HTML", reply_markup=kb)
        return


def _remove_kb():
    from keyboards import remove_kb
    return remove_kb


async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE,
                user: dict) -> None:
    q = update.callback_query
    data = q.data or ""
    uid = user["telegram_id"]
    parts = data.split(":")

    # همه‌ی مسیرهای nc: با اعتبارسنجی سخت‌گیرانه
    if data == "nc:noop":
        await q.answer()
        return

    if parts[0] == "nc" and parts[1] == "open" and len(parts) == 3 \
            and parts[2].lstrip("-").isdigit():
        await q.answer()
        await _show_center(q, uid, max(0, int(parts[2])))
        return

    if parts[0] == "nc" and parts[1] == "page" and len(parts) == 3 \
            and parts[2].lstrip("-").isdigit():
        await q.answer()
        await _show_center(q, uid, max(0, int(parts[2])))
        return

    if parts[0] == "nc" and parts[1] == "back":
        from keyboards import main_menu_kb
        db.set_state(uid, config.ST_MAIN)
        await q.answer()
        await q.message.reply_text("منوی اصلی:", reply_markup=main_menu_kb())
        return

    if parts[0] == "nc" and parts[1] == "readall":
        await q.answer()
        await q.message.reply_text(
            "❓ همه‌ی اعلان‌ها «خوانده‌شده» علامت بخورند؟",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ بله", callback_data="nc:readallyes"),
                InlineKeyboardButton("❌ نه", callback_data="nc:open:0")]]))
        return

    if parts[0] == "nc" and parts[1] == "readallyes":
        n = db.mark_all_notifications_read(uid)
        await q.answer(f"✅ {n} اعلان خوانده شد")
        await _show_center(q, uid, 0)
        return

    if parts[0] == "nc" and parts[1] == "view" and len(parts) == 3 \
            and parts[2].lstrip("-").isdigit():
        nid = int(parts[2])
        n = db.get_notification(nid)
        if not n:
            await q.answer("این اعلان پیدا نشد (شاید حذف شده باشد).", show_alert=True)
            return
        if n["user_id"] != uid:  # ⛔ امنیت: اعلانِ کاربر دیگر
            log.warning("notif forge attempt: uid=%s tried notif=%s", uid, nid)
            db.log_event("notif_forge", f"user={uid} notif={nid}")
            await q.answer(FORGE_ALERT, show_alert=True)
            return
        db.mark_notification_read(nid, uid)  # فقط همین یکی (شرط user_id در SQL)
        n = db.get_notification(nid)
        await q.answer()
        kb = []
        if n["action_type"]:
            kb.append([InlineKeyboardButton(
                ACTION_LABELS.get(n["action_type"], "👀 مشاهده"),
                callback_data=f"nc:act:{nid}")])
        kb.append([InlineKeyboardButton("⬅️ مرکز اعلان‌ها", callback_data="nc:open:0")])
        await q.message.reply_text(_view_text(n), parse_mode="HTML",
                                   reply_markup=InlineKeyboardMarkup(kb))
        return

    if parts[0] == "nc" and parts[1] == "act" and len(parts) == 3 \
            and parts[2].lstrip("-").isdigit():
        nid = int(parts[2])
        n = db.get_notification(nid)
        if not n:
            await q.answer("این اعلان پیدا نشد.", show_alert=True)
            return
        if n["user_id"] != uid:  # ⛔ امنیت: action اعلانِ کاربر دیگر
            log.warning("notif action forge: uid=%s tried notif=%s", uid, nid)
            db.log_event("notif_forge", f"user={uid} act={nid}")
            await q.answer(FORGE_ALERT, show_alert=True)
            return
        await q.answer()
        await _do_action(update, context, uid, n)
        return

    await q.answer()
