"""پنل مدیریت بگودیت — آمار، کاربران، صف، چت‌ها، گزارش‌ها، معرفی‌ها،
همگانی (با کنترل سیل و توقف)، بازخورد، کاربران تستی، تنظیمات."""
import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
import database as db
from keyboards import confirm_kb, main_menu_kb
from services import coins
from services import settings as S
from services import test_users
from utils import helpers as H

log = logging.getLogger("bagoodit.admin")

BC = {"stop": False, "running": False}


def _is_admin(uid: int) -> bool:
    return uid == config.ADMIN_ID


# ================= پنل =================
def _panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار", callback_data="adm:stats"),
         InlineKeyboardButton("👥 کاربران", callback_data="adm:users")],
        [InlineKeyboardButton("📡 صف انتظار", callback_data="adm:queue"),
         InlineKeyboardButton("💬 چت‌های فعال", callback_data="adm:chats")],
        [InlineKeyboardButton("⚠️ گزارش‌ها", callback_data="adm:reports"),
         InlineKeyboardButton("🎁 معرفی‌ها", callback_data="adm:refs")],
        [InlineKeyboardButton("📝 بازخوردها", callback_data="adm:fb"),
         InlineKeyboardButton("📣 پیام همگانی", callback_data="adm:broadcast")],
        [InlineKeyboardButton("🧪 کاربران تستی", callback_data="adm:test"),
         InlineKeyboardButton("⚙️ تنظیمات", callback_data="adm:settings")],
    ])


PANEL_TEXT = "🛠 <b>پنل مدیریت بگودیت</b>\nیکی از بخش‌ها را انتخاب کن:"


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not _is_admin(uid):
        return
    db.ensure_user(uid)
    db.set_state(uid, config.ST_MAIN)
    await update.message.reply_text(PANEL_TEXT, parse_mode="HTML",
                                    reply_markup=_panel_kb())


async def _back_to_panel(q) -> None:
    await q.message.reply_text(PANEL_TEXT, parse_mode="HTML", reply_markup=_panel_kb())


# ================= callbackها =================
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict) -> None:
    q = update.callback_query
    uid = q.from_user.id
    if not _is_admin(uid):
        await q.answer("فقط ادمین!")
        return
    data = q.data or ""
    parts = data.split(":")

    if data == "adm:stats":
        await q.answer()
        await q.message.reply_text(_stats_text(), parse_mode="HTML")
        return

    if data == "adm:users":
        db.set_state(uid, config.ST_ADMIN_FIND, {})
        await q.answer()
        await q.message.reply_text(
            "👥 شناسه کاربر را بفرست:\n• آیدی عددی تلگرام\n• یا شناسه ناشناس مثل <code>user51234</code>",
            parse_mode="HTML")
        return

    if data == "adm:queue":
        await q.answer()
        await q.message.reply_text(_queue_text(), parse_mode="HTML",
                                   reply_markup=_queue_kb())
        return

    if data == "adm:chats":
        await q.answer()
        await q.message.reply_text(_chats_text(), parse_mode="HTML",
                                   reply_markup=_chats_kb())
        return

    if data == "adm:reports":
        await q.answer()
        await q.message.reply_text(_reports_text(), parse_mode="HTML",
                                   reply_markup=_reports_kb())
        return

    if parts[1] == "rptview" and len(parts) == 3 and parts[2].isdigit():
        await q.answer()
        await q.message.reply_text(_report_detail(int(parts[2])), parse_mode="HTML",
                                   reply_markup=_report_actions_kb(int(parts[2])))
        return

    if parts[1] == "rban" and len(parts) == 4:
        tid, rid = int(parts[2]), int(parts[3])
        await ban_user(context, tid, admin_uid=uid)
        db.resolve_report(rid)
        await q.answer("کاربر مسدود و پرونده بسته شد ✅")
        return

    if parts[1] == "rdone" and len(parts) == 3:
        db.resolve_report(int(parts[2]))
        await q.answer("پرونده بسته شد ✅")
        return

    if data == "adm:refs":
        await q.answer()
        await q.message.reply_text(_refs_text(), parse_mode="HTML")
        return

    if data == "adm:fb":
        await q.answer()
        await q.message.reply_text(_feedback_text(), parse_mode="HTML")
        return

    if data == "adm:broadcast":
        if BC["running"]:
            await q.answer("یک همگانی در حال اجراست!")
            return
        db.set_state(uid, config.ST_ADMIN_BC, {})
        await q.answer()
        await q.message.reply_text(
            "📣 پیام همگانی را بفرست (متن، عکس، ویدیو…).\nبرای لغو /cancel را بزن.")
        return

    if data == "adm:bsend":
        await q.answer("شروع شد…")
        asyncio.create_task(_run_broadcast(context, uid))
        return

    if data == "adm:bcancel":
        db.set_state(uid, config.ST_MAIN, {})
        await q.answer("لغو شد.")
        await q.message.reply_text("همگانی لغو شد.", reply_markup=_panel_kb())
        return

    if data == "adm:bstop":
        BC["stop"] = True
        await q.answer("درخواست توقف ثبت شد ⏹")
        return

    if data == "adm:test":
        await q.answer()
        await q.message.reply_text(_test_text(), parse_mode="HTML",
                                   reply_markup=_test_kb())
        return

    if data == "adm:t_on":
        test_users.start_test_mode(S.get_int("test_mode_days"))
        await q.answer("تست‌مود روشن شد ✅")
        await q.message.reply_text(_test_text(), parse_mode="HTML",
                                   reply_markup=_test_kb())
        return

    if data == "adm:t_off":
        test_users.stop_test_mode(manual=True)
        await q.answer("تست‌مود خاموش شد ⏹")
        await q.message.reply_text(_test_text(), parse_mode="HTML",
                                   reply_markup=_test_kb())
        return

    if data == "adm:t_ext":
        test_users.start_test_mode(S.get_int("test_mode_days"))
        await q.answer("تمدید شد ✅")
        await q.message.reply_text(_test_text(), parse_mode="HTML",
                                   reply_markup=_test_kb())
        return

    if data == "adm:t_seed":
        await q.answer("در حال ساخت…")
        n = await asyncio.to_thread(test_users.generate_test_users, False)
        await q.message.reply_text(
            f"🧪 {n} کاربر تستی جدید ساخته شد." if n else "🧪 کاربران تستی از قبل موجودند.")
        return

    if data == "adm:t_del":
        await q.answer()
        await q.message.reply_text(
            "⚠️ <b>مطمئنی؟</b> همه‌ی کاربران تستی حذف می‌شوند (فقط <code>is_test_user=true</code>؛ "
            "چت‌های مرتبط بسته و تاریخچه تطبیقشان پاک می‌شود).",
            parse_mode="HTML",
            reply_markup=confirm_kb("adm:t_delyes", "adm:back", "🗑 بله، حذف کن", "❌ انصراف"))
        return

    if data == "adm:t_delyes":
        await q.answer("در حال حذف…")
        n = await asyncio.to_thread(db.delete_test_users)
        await q.message.reply_text(f"🗑 {n} کاربر تستی حذف شد.")
        return

    if data == "adm:t_avatars":
        await q.answer("در حال ساخت آواتارها… (چند ثانیه)")
        from services import avatars
        pool = await avatars.build_pool(context.bot)
        if not pool:
            await q.message.reply_text(
                "⚠️ ساخت استخر آواتار ناموفق بود؛ اول با ربات /start کن تا ادمین شناخته شود.")
            return
        S.set_value("avatar_pool", str(pool).replace("'", '"'))
        import json as _json
        S.set_value("avatar_pool", _json.dumps(pool, ensure_ascii=False))
        n = await asyncio.to_thread(db.assign_avatars_to_tests, pool)
        await q.message.reply_text(f"🖼 استخر آواتار ساخته شد ({len(pool)} عدد) و به {n} کاربر تستی تخصیص یافت.")
        return

    if data == "adm:settings":
        await q.answer()
        await q.message.reply_text(_settings_text(), parse_mode="HTML",
                                   reply_markup=_settings_kb())
        return

    if parts[1] == "set" and len(parts) == 3:
        key = parts[2]
        if key not in S.EDITABLE:
            await q.answer("کلید نامعتبر!")
            return
        db.set_state(uid, config.ST_ADMIN_SET, {"set_key": key})
        await q.answer()
        cur = S.get(key)
        await q.message.reply_text(
            f"⚙️ <b>{H.esc(S.EDITABLE[key])}</b>\nمقدار فعلی: <code>{H.esc(cur)}</code>\n\nمقدار جدید را بفرست:")
        return

    if parts[1] == "qkick" and len(parts) == 3:
        from services import matching as M
        await M.cancel_search(context, int(parts[2]))
        await q.answer("از صف خارج شد ✅")
        await q.message.reply_text(_queue_text(), parse_mode="HTML",
                                   reply_markup=_queue_kb())
        return

    if parts[1] == "cclose" and len(parts) == 3:
        cid = int(parts[2])
        res = db.close_chat(cid, closer_id=uid)
        if res:
            for t in res:
                if t > 0:
                    await H.notify(context.bot, t, "⛔️ چت توسط مدیریت بسته شد.",
                                   reply_markup=main_menu_kb())
        await q.answer("بسته شد ⛔️")
        return

    # ---------- مدیریت کاربر ----------
    if parts[1] == "ban" and len(parts) == 3:
        await ban_user(context, int(parts[2]), admin_uid=uid)
        await q.answer("مسدود شد 🚫")
        return

    if parts[1] == "unban" and len(parts) == 3:
        await unban_user(context, int(parts[2]))
        await q.answer("رفع مسدودی ✅")
        return

    if parts[1] == "addcoin" and len(parts) == 3:
        await q.answer()
        _start_coin(uid, int(parts[2]), "add")
        await q.message.reply_text("➕ مقدار سکه را بفرست (عدد):")
        return

    if parts[1] == "subcoin" and len(parts) == 3:
        await q.answer()
        _start_coin(uid, int(parts[2]), "sub")
        await q.message.reply_text("➖ مقدار سکه را بفرست (عدد):")
        return

    if parts[1] == "msg" and len(parts) == 3:
        db.set_state(uid, config.ST_ADMIN_MSG, {"msg_to": int(parts[2])})
        await q.answer()
        await q.message.reply_text("📩 متن پیام برای این کاربر را بنویس:")
        return

    if parts[1] == "chatsu" and len(parts) == 3:
        await q.answer()
        await q.message.reply_text(_user_chats_text(int(parts[2])), parse_mode="HTML")
        return

    if parts[1] == "deltest" and len(parts) == 3:
        tid = int(parts[2])
        await q.answer()
        await q.message.reply_text(
            "⚠️ این کاربر تستی حذف شود؟", parse_mode="HTML",
            reply_markup=confirm_kb(f"adm:deltestyes:{tid}", "adm:back"))
        return

    if parts[1] == "deltestyes" and len(parts) == 3:
        tid = int(parts[2])
        n = db.x("DELETE FROM users WHERE is_test_user=1 AND telegram_id=?", (tid,))
        await q.answer("حذف شد 🗑" if n else "یافت نشد!")
        return

    if data == "adm:back":
        db.set_state(uid, config.ST_MAIN, {})
        await q.answer()
        await _back_to_panel(q)
        return

    await q.answer()


def _start_coin(uid: int, tid: int, mode: str) -> None:
    db.set_state(uid, config.ST_ADMIN_COIN, {"coin_to": tid, "coin_mode": mode})


# ================= متن‌های بخش‌ها =================
def _stats_text() -> str:
    s = db.stats()
    return (
        "📊 <b>آمار بگودیت</b>\n\n"
        f"👥 کل کاربران: {s['users_total']} (واقعی: {s['users_real']} | 🧪 تستی: {s['users_test']})\n"
        f"👦 پسر: {s['male']} | 👧 دختر: {s['female']}\n"
        f"💬 چت‌ها: {s['chats_active']} فعال از {s['chats_total']} کل\n"
        f"📡 در صف انتظار: {s['queue']}\n"
        f"⚠️ گزارش‌های باز: {s['reports_open']}\n"
        f"📝 بازخوردهای باز: {s['feedback_open']}\n"
        f"🎁 کل دعوت‌های موفق: {s['referrals_total']}\n"
        f"🪙 سکه‌های توزیع‌شده: {s['coins_granted']}")


def _queue_text() -> str:
    rows = db.list_state(config.ST_SEARCHING)
    if not rows:
        return "📡 صف انتظار خالی است."
    lines = ["📡 <b>صف انتظار</b>\n"]
    for r in rows[:15]:
        ctx = db.get_ctx(r)
        joined = (ctx.get("joined") or "—")[:16].replace("T", " ")
        lines.append(f"• <code>{r['bot_user_id']}</code> | "
                     f"{H.gender_label(r['gender'])} {r['age']} | {H.esc(r['city'])} | از {joined}")
    return "\n".join(lines)


def _queue_kb() -> InlineKeyboardMarkup:
    rows = db.list_state(config.ST_SEARCHING)
    kb = []
    for r in rows[:15]:
        kb.append([InlineKeyboardButton(
            f"↩️ خروج {r['bot_user_id']}", callback_data=f"adm:qkick:{r['telegram_id']}")])
    kb.append([InlineKeyboardButton("🔄 تازه‌سازی", callback_data="adm:queue")])
    kb.append([InlineKeyboardButton("⬅️ پنل", callback_data="adm:back")])
    return InlineKeyboardMarkup(kb)


def _chats_text() -> str:
    chats = db.active_chats_list()
    if not chats:
        return "💬 چت فعالی وجود ندارد."
    lines = ["💬 <b>چت‌های فعال</b>\n"]
    for c in chats[:15]:
        tag = " 🧪" if c["is_test_chat"] else ""
        u1 = db.get_user(c["user1_id"])
        u2 = db.get_user(c["user2_id"])
        lines.append(f"• #{c['chat_id']}: <code>{u1['bot_user_id']}</code> ↔ "
                     f"<code>{u2['bot_user_id']}</code> | {c['init_kind']}{tag}")
    return "\n".join(lines)


def _chats_kb() -> InlineKeyboardMarkup:
    chats = db.active_chats_list()
    kb = []
    for c in chats[:15]:
        kb.append([InlineKeyboardButton(f"⛔️ بستن #{c['chat_id']}",
                                        callback_data=f"adm:cclose:{c['chat_id']}")])
    kb.append([InlineKeyboardButton("🔄 تازه‌سازی", callback_data="adm:chats")])
    kb.append([InlineKeyboardButton("⬅️ پنل", callback_data="adm:back")])
    return InlineKeyboardMarkup(kb)


def _reports_text() -> str:
    rows = db.open_reports()
    if not rows:
        return "⚠️ گزارش بازی وجود ندارد. 🎉"
    lines = ["⚠️ <b>گزارش‌های باز</b>\n"]
    for r in rows[:15]:
        rep = db.get_user(r["reporter_id"])
        tgt = db.get_user(r["reported_id"])
        lines.append(f"• #{r['report_id']}: <code>{rep['bot_user_id']}</code> علیه "
                     f"<code>{tgt['bot_user_id']}</code> — {H.esc(r['reason'])}")
    return "\n".join(lines)


def _reports_kb() -> InlineKeyboardMarkup:
    rows = db.open_reports()
    kb = [[InlineKeyboardButton(f"مشاهده #{r['report_id']}", callback_data=f"adm:rptview:{r['report_id']}")]
          for r in rows[:15]]
    kb.append([InlineKeyboardButton("🔄 تازه‌سازی", callback_data="adm:reports")])
    kb.append([InlineKeyboardButton("⬅️ پنل", callback_data="adm:back")])
    return InlineKeyboardMarkup(kb)


def _report_detail(rid: int) -> str:
    r = db.get_report(rid)
    if not r:
        return "گزارش یافت نشد."
    rep = db.get_user(r["reporter_id"])
    tgt = db.get_user(r["reported_id"])
    return (f"⚠️ <b>گزارش #{r['report_id']}</b>\n"
            f"از: {H.esc(rep['nickname'])} (<code>{rep['bot_user_id']}</code>)\n"
            f"علیه: {H.esc(tgt['nickname'])} (<code>{tgt['bot_user_id']}</code>) | "
            f"بن‌شده: {'بله' if tgt['banned'] else 'نه'}\n"
            f"دلیل: {H.esc(r['reason'])}\n"
            f"چت: #{r['chat_id']}\nزمان: {r['created_at'][:16]}")


def _report_actions_kb(rid: int) -> InlineKeyboardMarkup:
    r = db.get_report(rid)
    kb = []
    if r:
        kb.append([InlineKeyboardButton("🚫 مسدودسازی متخلف", callback_data=f"adm:rban:{r['reported_id']}:{rid}")])
    kb.append([InlineKeyboardButton("✅ بستن پرونده", callback_data=f"adm:rdone:{rid}")])
    kb.append([InlineKeyboardButton("⬅️ گزارش‌ها", callback_data="adm:reports")])
    return InlineKeyboardMarkup(kb)


def _refs_text() -> str:
    tops = db.top_referrers(10)
    total = db.stats()["referrals_total"]
    if not tops:
        return f"🎁 کل دعوت‌های موفق: {total}\nهنوز دعوتی ثبت نشده."
    lines = [f"🎁 <b>معرفی‌ها</b> — مجموع: {total}\n", "<b>برترین‌ها:</b>"]
    for t in tops:
        u = db.get_user(t["tid"])
        if u:
            lines.append(f"• {H.esc(u['nickname'])} (<code>{u['bot_user_id']}</code>): {t['c']} نفر")
    return "\n".join(lines)


def _feedback_text() -> str:
    rows = db.open_feedback()
    if not rows:
        return "📝 بازخورد بازی وجود ندارد."
    lines = ["📝 <b>بازخوردهای باز</b>\n"]
    for f in rows[:15]:
        u = db.get_user(f["user_id"])
        lines.append(f"• #{f['fb_id']} از <code>{u['bot_user_id'] if u else f['user_id']}</code>: "
                     f"{H.esc(f['text'][:60])}")
    lines.append("\n💬 برای پاسخ، از دکمه‌ی «پاسخ» روی اعلان بازخورد استفاده کن.")
    return "\n".join(lines)


def _user_chats_text(tid: int) -> str:
    rows = db.user_chats(tid, 10)
    if not rows:
        return "این کاربر چتی ندارد."
    lines = ["💬 <b>چت‌های اخیر کاربر</b>\n"]
    for c in rows:
        p = db.get_user(c["partner"])
        lines.append(f"• #{c['chat_id']} با <code>{p['bot_user_id'] if p else c['partner']}</code> | "
                     f"{c['state']} | {c['started_at'][:16]}")
    return "\n".join(lines)


# ================= کاربر تستی =================
def _test_text() -> str:
    exp = (S.get("test_mode_expires_at") or "—")[:16].replace("T", " ")
    enabled = test_users.test_mode_active()
    c = test_users.test_counts()
    mode = "🟢 روشن" if enabled else "🔴 خاموش"
    return ("🧪 <b>مدیریت کاربران تستی</b>\n\n"
            f"وضعیت تست‌مود: {mode}\n"
            f"انقضا: {exp}\n"
            f"تعداد کاربران تستی: {c['total']} (دختر: {c['female']} | پسر: {c['male']})\n"
            f"اولویت کاربران واقعی: {'بله' if S.get_bool('real_users_first') else 'خیر'}")


def _test_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 روشن", callback_data="adm:t_on"),
         InlineKeyboardButton("⏹ خاموش", callback_data="adm:t_off")],
        [InlineKeyboardButton("🔁 تمدید ۷ روز", callback_data="adm:t_ext"),
         InlineKeyboardButton("🧬 ساخت کاربران تستی", callback_data="adm:t_seed")],
        [InlineKeyboardButton("🖼 ساخت آواتارها", callback_data="adm:t_avatars")],
        [InlineKeyboardButton("🗑 حذف همه کاربران تستی", callback_data="adm:t_del")],
        [InlineKeyboardButton("⬅️ پنل", callback_data="adm:back")],
    ])


# ================= تنظیمات =================
def _settings_text() -> str:
    lines = ["⚙️ <b>تنظیمات (برای تغییر روی مقدار بزن)</b>\n"]
    for key, label in S.EDITABLE.items():
        lines.append(f"• {label}: <code>{H.esc(S.get(key))}</code>")
    return "\n".join(lines)


def _settings_kb() -> InlineKeyboardMarkup:
    kb = []
    keys = list(S.EDITABLE.keys())
    for i in range(0, len(keys), 2):
        row = [InlineKeyboardButton(S.EDITABLE[k][:18], callback_data=f"adm:set:{k}")
               for k in keys[i:i + 2]]
        kb.append(row)
    kb.append([InlineKeyboardButton("⬅️ پنل", callback_data="adm:back")])
    return InlineKeyboardMarkup(kb)


# ================= متن‌های هندلر متن =================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      user: dict) -> None:
    uid = user["telegram_id"]
    ctx = db.get_ctx(user)
    state = user["state"]
    text = (update.message.text or "").strip()

    if state == config.ST_ADMIN_FIND:
        target = db.search_user_any(text)
        if not target:
            await update.message.reply_text("❌ کاربر یافت نشد.")
            return
        await _show_user_admin(update, context, target)
        return

    if state == config.ST_ADMIN_COIN:
        tid = ctx.get("coin_to")
        mode = ctx.get("coin_mode", "add")
        if not text.lstrip("-").isdigit():
            await update.message.reply_text("فقط عدد بفرست:")
            return
        amount = abs(int(text))
        if amount == 0 or amount > 1000000:
            await update.message.reply_text("مقدار نامعتبر است.")
            return
        delta = amount if mode == "add" else -amount
        bal = db.adjust_coins(tid, delta, f"admin:{mode}")
        if bal is None:
            await update.message.reply_text("خطا در تغییر موجودی.")
            return
        db.set_state(uid, config.ST_MAIN, {})
        await update.message.reply_text(f"✅ انجام شد. موجودی جدید: {bal} سکه")
        t = db.get_user(tid)
        if not t["is_test_user"]:
            label = "اضافه" if mode == "add" else "کسر"
            await H.notify(context.bot, tid,
                           f"🪙 مدیریت {amount} سکه به حساب تو {label} کرد.\nموجودی جدید: {bal}")
        return

    if state == config.ST_ADMIN_MSG:
        tid = ctx.get("msg_to")
        db.set_state(uid, config.ST_MAIN, {})
        ok = await H.notify(context.bot, tid, f"📩 <b>پیام از مدیریت بگودیت:</b>\n\n{H.esc(text)}")
        await update.message.reply_text("✅ ارسال شد." if ok else "❌ ارسال ناموفق (کاربر ربات را بلاک کرده).")
        return

    if state == config.ST_ADMIN_FB:
        fid = ctx.get("fb_id")
        fb = db.get_feedback(fid)
        if not fb:
            db.set_state(uid, config.ST_MAIN, {})
            await update.message.reply_text("بازخورد یافت نشد.")
            return
        db.answer_feedback(fid, text)
        db.set_state(uid, config.ST_MAIN, {})
        ok = await H.notify(context.bot, fb["user_id"],
                            f"💬 <b>پاسخ مدیریت بگودیت به پیام تو:</b>\n\n{H.esc(text)}")
        await update.message.reply_text("✅ پاسخ ارسال شد." if ok else "❌ ارسال ناموفق.")
        return

    if state == config.ST_ADMIN_BC:
        db.set_state(uid, config.ST_MAIN, {"bc_mid": update.message.message_id,
                                           "bc_cid": update.effective_chat.id})
        await update.message.reply_text(
            "📣 این پیام برای همه‌ی کاربران واقعی ارسال شود؟",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ ارسال", callback_data="adm:bsend"),
                InlineKeyboardButton("❌ لغو", callback_data="adm:bcancel")]]))
        return

    if state == config.ST_ADMIN_SET:
        key = ctx.get("set_key")
        if key not in S.EDITABLE:
            db.set_state(uid, config.ST_MAIN, {})
            return
        if key in S.BOOL_KEYS:
            v = text.strip().lower()
            if v not in ("true", "false", "روشن", "خاموش"):
                await update.message.reply_text("فقط true یا false:")
                return
            S.set_value(key, "true" if v in ("true", "روشن") else "false")
        else:
            if not text.isdigit():
                await update.message.reply_text("فقط عدد بفرست:")
                return
            S.set_value(key, int(text))
        db.set_state(uid, config.ST_MAIN, {})
        await update.message.reply_text(f"✅ ثبت شد: {S.EDITABLE[key]} = {S.get(key)}")
        return


async def _show_user_admin(update, context, target: dict) -> None:
    uid = update.effective_user.id
    card = H.user_card(target, show_coins=True)
    btns = []
    if target["banned"]:
        btns.append([InlineKeyboardButton("✅ رفع مسدودی", callback_data=f"adm:unban:{target['telegram_id']}")])
    else:
        btns.append([InlineKeyboardButton("🚫 مسدودسازی", callback_data=f"adm:ban:{target['telegram_id']}")])
    btns.append([InlineKeyboardButton("➕ سکه", callback_data=f"adm:addcoin:{target['telegram_id']}"),
                 InlineKeyboardButton("➖ سکه", callback_data=f"adm:subcoin:{target['telegram_id']}")])
    btns.append([InlineKeyboardButton("📩 پیام", callback_data=f"adm:msg:{target['telegram_id']}"),
                 InlineKeyboardButton("💬 چت‌ها", callback_data=f"adm:chatsu:{target['telegram_id']}")])
    if target["is_test_user"]:
        btns.append([InlineKeyboardButton("🗑 حذف کاربر تستی", callback_data=f"adm:deltest:{target['telegram_id']}")])
    btns.append([InlineKeyboardButton("⬅️ پنل", callback_data="adm:back")])
    db.set_state(uid, config.ST_MAIN, {})
    if target["avatar_file_id"]:
        try:
            await context.bot.send_photo(chat_id=uid, photo=target["avatar_file_id"],
                                         caption=card, parse_mode="HTML",
                                         reply_markup=InlineKeyboardMarkup(btns))
            return
        except Exception:
            pass
    await update.message.reply_text(card, parse_mode="HTML",
                                    reply_markup=InlineKeyboardMarkup(btns))


# ================= بن / رفع بن =================
async def ban_user(context, tid: int, admin_uid=None) -> None:
    u = db.get_user(tid)
    if not u or u["is_test_user"]:
        return
    db.update_user(tid, banned=1)
    # خروج از صف + بازگشت سکه
    if u["state"] == config.ST_SEARCHING:
        from services import matching as M
        crit = M.criteria_from_ctx(db.get_ctx(u))
        cost = M.cost_of(crit.get("kind", "random"))
        if cost > 0:
            coins.refund(tid, cost, crit.get("kind", "random"))
        db.set_state(tid, config.ST_MAIN, {})
    # بستن چت فعال
    chat = db.get_active_chat(tid)
    if chat:
        pid = db.partner_id_of(chat, tid)
        db.close_chat(chat["chat_id"], closer_id=None)
        await H.notify(context.bot, pid,
                       "❌ <b>طرف مقابل توسط مدیریت مسدود شد.</b>\nچت بسته شد.",
                       reply_markup=main_menu_kb())
    await H.notify(context.bot, tid, "🚫 <b>دسترسی شما به بگودیت مسدود شد.</b>")


async def unban_user(context, tid: int) -> None:
    u = db.get_user(tid)
    if not u:
        return
    db.update_user(tid, banned=0)
    db.set_state(tid, config.ST_MAIN, {})
    await H.notify(context.bot, tid, "✅ مسدودی تو رفع شد؛ خوش برگشتی!",
                   reply_markup=main_menu_kb())


# ================= پیام همگانی =================
async def _run_broadcast(context, admin_uid: int) -> None:
    ctx_user = db.get_user(admin_uid)
    ctx = db.get_ctx(ctx_user)
    mid, cid = ctx.get("bc_mid"), ctx.get("bc_cid")
    if not mid or not cid:
        return
    users = db.all_real_user_ids()
    total = len(users)
    if total == 0:
        await H.notify(context.bot, admin_uid, "کاربری برای ارسال نیست.")
        return
    BC["stop"] = False
    BC["running"] = True
    ok = fail = 0
    sent_msg = await context.bot.send_message(
        chat_id=admin_uid,
        text=f"📣 ارسال: 0/{total} | ✅ 0 | ❌ 0")
    pmsg = sent_msg.message_id
    for i, tid in enumerate(users, 1):
        if BC["stop"]:
            break
        try:
            await context.bot.copy_message(chat_id=tid, from_chat_id=cid, message_id=mid)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(config.BROADCAST_SLEEP)  # کنترل سیل
        if i % config.BROADCAST_PROGRESS_EVERY == 0:
            try:
                await context.bot.edit_message_text(
                    f"📣 ارسال: {i}/{total} | ✅ {ok} | ❌ {fail}", chat_id=admin_uid,
                    message_id=pmsg)
            except Exception:
                pass
    stopped = BC["stop"]
    BC["running"] = False
    try:
        await context.bot.edit_message_text(
            f"{'⏹ متوقف شد' if stopped else '✅ تمام شد'} | 📣 "
            f"ارسال: {ok + fail}/{total} | ✅ {ok} | ❌ {fail}",
            chat_id=admin_uid, message_id=pmsg)
    except Exception:
        pass
