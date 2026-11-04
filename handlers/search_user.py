"""جست‌وجوی کاربر با شناسه ناشناس + درخواست چت (قبول/رد)."""
import logging
import random
import re

from telegram import Update
from telegram.ext import ContextTypes

import config
import database as db
from keyboards import main_menu_kb, request_kb
from services import coins
from utils import helpers as H

log = logging.getLogger("bagoodit.search")

USER_ID_RE = re.compile(r"^/?user[45]\d{4,5}$", re.IGNORECASE)


async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       user: dict) -> None:
    uid = user["telegram_id"]
    text = (update.message.text or "").strip()
    if text == "/cancel":
        db.set_state(uid, config.ST_MAIN)
        await update.message.reply_text("لغو شد.", reply_markup=main_menu_kb())
        return
    if not db.is_registered(user):
        await update.message.reply_text("اول ثبت‌نام را کامل کن؛ /start را بزن.")
        return
    if not USER_ID_RE.match(text):
        await update.message.reply_text(
            "فرمت درست نیست؛ مثل <code>user51234</code> بفرست.",
            parse_mode="HTML")
        return
    await _show_target(update, context, user, text)


async def _show_target(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       user: dict, raw: str) -> None:
    uid = user["telegram_id"]
    target = db.get_user_by_bot_id(raw.strip().lstrip("/").lower())
    if not target:
        await update.message.reply_text("❌ کاربری با این شناسه پیدا نشد.")
        return
    if target["telegram_id"] == uid:
        await update.message.reply_text("😄 این شناسه خودت است!")
        return
    if target["banned"]:
        await update.message.reply_text("❌ این حساب در دسترس نیست.")
        return
    if db.get_active_chat(target["telegram_id"]):
        await update.message.reply_text(
            "💬 این کاربر الان در چت دیگری است؛ کمی بعد دوباره امتحان کن.")
        return
    if target["state"] == config.ST_NONE:
        await update.message.reply_text("❌ این حساب ثبت‌نام را کامل نکرده است.")
        return

    card = H.user_card(target, show_contact_hint=True)
    if target["avatar_file_id"]:
        try:
            await context.bot.send_photo(chat_id=uid, photo=target["avatar_file_id"],
                                         caption=card, parse_mode="HTML")
        except Exception:
            await update.message.reply_text(card, parse_mode="HTML")
    else:
        await update.message.reply_text(card, parse_mode="HTML")

    if target["is_test_user"]:
        # کاربر تستی → درخواست به‌صورت خودکار بعد از چند ثانیه قبول می‌شود
        rid = db.create_chat_request(uid, target["telegram_id"])
        if rid is None:
            await update.message.reply_text("⏳ درخواست قبلی تو هنوز در انتظار است.")
            return
        await update.message.reply_text("📨 درخواست چت ارسال شد؛ منتظر پاسخ بمان…")
        delay = random.uniform(3, 6)
        context.job_queue.run_once(_auto_accept_job, when=delay,
                                   data={"rid": rid}, name=f"autoacc:{rid}")
        return

    # کاربر واقعی → دکمه درخواست
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("💬 درخواست چت", callback_data=f"usr:req:{target['telegram_id']}")]])
    await update.message.reply_text("برای شروع گفت‌وگو درخواست بفرست:", reply_markup=kb)


async def _auto_accept_job(context) -> None:
    """قبول خودکار درخواست توسط کاربر تستی."""
    rid = context.job.data["rid"]
    await _accept_request(context, rid, auto=True)


async def _accept_request(context, rid: int, auto=False) -> bool:
    req = db.get_request(rid)
    if not req or req["status"] != "PENDING":
        return False
    from_uid, to_uid = req["from_uid"], req["to_uid"]
    sender = db.get_user(from_uid)
    target = db.get_user(to_uid)
    if not sender or not target or sender["banned"] or target["banned"]:
        db.set_request_status(rid, "CANCELED")
        return False
    if db.get_active_chat(from_uid) or db.get_active_chat(to_uid):
        db.set_request_status(rid, "EXPIRED")
        await H.notify(context.bot, from_uid,
                       "⏳ درخواست معلق ماند (طرف در چت دیگر است).")
        return False
    if not db.set_request_status(rid, "ACCEPTED"):
        return False
    # اگر هر یک در صف جست‌وجو بود، هزینه‌اش برگردد
    for u in (sender, target):
        if u["state"] == config.ST_SEARCHING and not u["is_test_user"]:
            from services import matching as M
            crit = M.criteria_from_ctx(db.get_ctx(u))
            M_cost = M.cost_of(crit.get("kind", "random"))
            if M_cost > 0:
                coins.refund(u["telegram_id"], M_cost, crit.get("kind", "random"))
    cap = random.randint(6, 10) if target["is_test_user"] else None
    cid = db.pair_users(from_uid, to_uid, "request",
                        b_is_test=target["is_test_user"], test_replies_cap=cap)
    if cid is None:
        await H.notify(context.bot, from_uid, "⏳ این درخواست دیگر قابل قبول نیست.")
        return False
    from keyboards import chat_kb
    await H.notify(context.bot, from_uid,
                   "✅ <b>درخواست تو قبول شد!</b>\nچت شروع شد 🎉",
                   reply_markup=chat_kb())
    if target["is_test_user"]:
        from services import auto_reply, matching as M
        await H.notify(context.bot, from_uid,
                       "🧪 <i>این حساب تستی بگودیت است (کاربر واقعی نیست).</i>")
        db.bump_test_reply(cid)
        db.set_last_reply(cid, "")
        delay = random.uniform(3, 8)
        context.job_queue.run_once(auto_reply.greeting_job, when=delay,
                                   data={"chat_id": cid, "test_uid": to_uid,
                                         "real_uid": from_uid}, name=f"tgreet:{cid}")
    else:
        sender_card = H.user_card(sender)
        await H.notify(context.bot, to_uid,
                       f"✅ <b>درخواست چت قبول شد!</b>\n\n{sender_card}",
                       reply_markup=chat_kb())
    return True


async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict) -> None:
    q = update.callback_query
    data = q.data or ""
    uid = q.from_user.id
    parts = data.split(":")

    if parts[0] == "usr" and parts[1] == "req" and parts[2].lstrip("-").isdigit():
        tid = int(parts[2])
        sender = db.get_user(uid)
        if not sender or not db.is_registered(sender):  # گیت ثبت‌نام برای درخواست‌دهنده
            await q.answer("اول ثبت‌نام را کامل کن!")
            return
        target = db.get_user(tid)
        if not target or target["telegram_id"] == uid or target["banned"]:
            await q.answer("در دسترس نیست!")
            return
        if db.get_active_chat(tid) or db.get_active_chat(uid):
            await q.answer("یکی از دو طرف در چت است.")
            return
        rid = db.create_chat_request(uid, tid)
        if rid is None:
            await q.answer("درخواست قبلی هنوز در انتظار است.")
            return
        await q.answer("درخواست ارسال شد ✅")
        card = H.user_card(sender, show_contact_hint=True)
        if sender["avatar_file_id"]:
            try:
                await context.bot.send_photo(chat_id=tid, photo=sender["avatar_file_id"],
                                             caption=f"📨 <b>درخواست چت جدید!</b>\n\n{card}",
                                             parse_mode="HTML", reply_markup=request_kb(rid))
            except Exception:
                await H.notify(context.bot, tid,
                               f"📨 <b>درخواست چت جدید!</b>\n\n{card}",
                               reply_markup=request_kb(rid))
        else:
            await H.notify(context.bot, tid,
                           f"📨 <b>درخواست چت جدید!</b>\n\n{card}",
                           reply_markup=request_kb(rid))
        await q.message.reply_text("📨 درخواست چت فرستاده شد؛ منتظر پاسخ او بمان.")
        return

    if parts[0] == "crq" and parts[1] in ("acc", "dec") and parts[2].isdigit():
        rid = int(parts[2])
        req = db.get_request(rid)
        if not req or req["status"] != "PENDING":
            await q.answer("این درخواست دیگر معتبر نیست.")
            return
        if req["to_uid"] != uid:  # امنیت: فقط گیرنده حق تصمیم دارد
            await q.answer("این درخواست مال تو نیست!")
            return
        if parts[1] == "acc":
            ok = await _accept_request(context, rid, auto=False)
            if ok:
                await q.answer("قبول شد ✅")
                try:
                    await q.message.edit_reply_markup()
                except Exception:
                    pass
            else:
                await q.answer("درخواست قابل اجرا نیست.")
            return
        # رد
        db.set_request_status(rid, "DECLINED")
        await q.answer("رد شد.")
        try:
            await q.message.edit_reply_markup()
        except Exception:
            pass
        await H.notify(context.bot, req["from_uid"],
                       "❌ متأسفانه درخواست چت تو رد شد.")
        return

    await q.answer()
