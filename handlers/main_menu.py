"""منوی اصلی: پروفایل، سکه‌ها، معرفی، بازخورد، راهنما."""
from telegram import Update
from telegram.ext import ContextTypes

import config
import database as db
from keyboards import (BTN_ANON_CHAT, BTN_COINS, BTN_FEEDBACK, BTN_HELP,
                       BTN_PROFILE, BTN_REFERRAL, BTN_SEARCH_USER, coins_kb,
                       main_menu_kb, match_menu_kb, profile_kb, remove_kb)
from services import settings as S
from utils import helpers as H


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      user: dict) -> None:
    uid = user["telegram_id"]
    text = (update.message.text or "").strip()

    # جست‌وجوی کاربر با شناسه، حتی از منوی اصلی
    if _is_user_query(text):
        from handlers import search_user
        await search_user.handle_input(update, context, user)
        return

    if text == BTN_ANON_CHAT:
        db.set_state(uid, config.ST_MATCH_MENU)
        costs = _costs_line()
        await update.message.reply_text(
            "💬 <b>منوی چت ناشناس</b>\n\nنوع جست‌وجو را انتخاب کن:" + costs,
            parse_mode="HTML", reply_markup=match_menu_kb())
        return

    if text == BTN_SEARCH_USER:
        db.set_state(uid, config.ST_SEARCH_USER, {})
        await update.message.reply_text(
            "🔍 <b>جست‌وجوی کاربر</b>\n\nشناسه ناشناس طرف را بفرست؛ مثل:\n"
            "<code>/user51234</code> یا <code>user51234</code>\n\n"
            "برای لغو: /cancel", parse_mode="HTML", reply_markup=remove_kb)
        return

    if text == BTN_PROFILE:
        await show_profile(update, context, uid)
        return

    if text == BTN_COINS:
        bal = db.get_balance(uid)
        await update.message.reply_text(
            f"🪙 <b>موجودی سکه‌های تو: {bal}</b>\n\n"
            "هزینه‌ها:\n"
            f"• 🔵 جست‌وجوی دختر/پسر: {S.get_int('coin_girl')}/{S.get_int('coin_boy')} سکه\n"
            f"• 🔴 افراد نزدیک: {S.get_int('coin_nearby')} سکه\n"
            f"• 🟣 جست‌وجوی پیشرفته: {S.get_int('coin_filter')} سکه\n"
            "• 🟢 چت تصادفی: رایگان!",
            parse_mode="HTML", reply_markup=coins_kb())
        return

    if text == BTN_REFERRAL:
        username = config.BOT_USERNAME or "this_bot"
        link = f"https://t.me/{username}?start=ref{uid}"
        cnt = db.referral_count(uid)
        await update.message.reply_text(
            "🎁 <b>دعوت دوستان</b>\n\nلینک اختصاصی تو:\n"
            f"<code>{H.esc(link)}</code>\n\n"
            f"• به‌ازای هر دوست که با لینک تو بیاید: 🪙 {S.get_int('referral_reward')} سکه\n"
            f"• دعوت‌های موفق تا کنون: {cnt}\n\n"
            "لینک را برای دوستانت بفرست؛ با اولین /start آن‌ها سکه می‌گیری.",
            parse_mode="HTML")
        return

    if text == BTN_FEEDBACK:
        db.set_state(uid, config.ST_FEEDBACK, {})
        await update.message.reply_text(
            "📝 <b>بازخورد و پشتیبانی</b>\n\nپیامت را بنویس؛ مستقیم برای مدیریت "
            "فرستاده می‌شود و جوابش همین‌جا می‌رسد.\nبرای لغو: /cancel",
            parse_mode="HTML", reply_markup=remove_kb)
        return

    if text == BTN_HELP:
        await send_help(update, context)
        return

    await update.message.reply_text("از دکمه‌های منو استفاده کن 👇",
                                    reply_markup=main_menu_kb())


def _is_user_query(text: str) -> bool:
    t = text.strip().lstrip("/").lower()
    return t.startswith("user") and t[4:].isdigit() and len(t) >= 8


def _costs_line() -> str:
    return ("\n\n🟢 تصادفی: رایگان | 🔵 دختر/پسر: "
            f"{S.get_int('coin_girl')}/{S.get_int('coin_boy')} | 🔴 نزدیک: "
            f"{S.get_int('coin_nearby')} | 🟣 پیشرفته: {S.get_int('coin_filter')} سکه")


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int) -> None:
    user = db.get_user(uid)
    if not user:
        return
    db.set_state(uid, config.ST_MAIN)
    card = H.user_card(user, show_coins=True)
    if user["avatar_file_id"]:
        try:
            await context.bot.send_photo(chat_id=uid, photo=user["avatar_file_id"],
                                         caption=card, parse_mode="HTML",
                                         reply_markup=profile_kb(bool(user["avatar_file_id"])))
            return
        except Exception:
            pass
    await update.effective_message.reply_text(card, parse_mode="HTML",
                                              reply_markup=profile_kb(bool(user["avatar_file_id"])))


async def send_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "ℹ️ <b>راهنمای بگودیت</b>\n\n"
        "🟢 <b>چت تصادفی</b> — رایگان؛ با یک نفر تصادفی حرف بزن.\n"
        "🔵 <b>جست‌وجوی دختر/پسر</b> — با سکه، جنس مخاصم را انتخاب کن.\n"
        "🔴 <b>افراد نزدیک</b> — اول هم‌شهری‌ها، بعد هم‌استانی‌ها.\n"
        "🟣 <b>جست‌وجوی پیشرفته</b> — فیلتر سن + شهر.\n"
        "🔍 <b>جست‌وجوی کاربر</b> — با شناسه مثل <code>user51234</code>.\n"
        "🎁 <b>دعوت دوستان</b> — با هر دعوت موفق سکه بگیر.\n"
        "📝 <b>بازخورد</b> — پیامت مستقیم به مدیریت می‌رسد.\n\n"
        "⚠️ قوانین: احترام، بدون توهین و محتوای غیراخلاقی؛ تخلف = مسدودسازی.\n"
        "دستورهای کاربردی: /menu لغو و بازگشت | /cancel لغو عملیات",
        parse_mode="HTML", reply_markup=main_menu_kb())


# ---------------- callbackهای پروفایل و سکه ----------------
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict) -> None:
    q = update.callback_query
    data = q.data or ""
    uid = user["telegram_id"]

    if data == "pf:back":
        db.set_state(uid, config.ST_MAIN)
        await q.answer()
        await q.message.reply_text("منوی اصلی:", reply_markup=main_menu_kb())
        return

    if data == "pf:noop":
        await q.answer()
        return

    if data == "pf:delphoto":
        db.update_user(uid, avatar_file_id=None)
        await q.answer("عکس حذف شد ✅")
        await show_profile_cb(q, uid)
        return

    if data.startswith("pf:edit:"):
        field = data.split(":")[2]
        ctx = {"edit": field}
        if field == "photo":
            from keyboards import skip_photo_kb
            db.set_state(uid, config.ST_REG_PHOTO, ctx)
            await q.answer()
            await q.message.reply_text(
                "🖼 عکس جدید را بفرست (برای رد کردن، دکمه رد را بزن):",
                reply_markup=skip_photo_kb())
            return
        if field == "gender":
            from keyboards import gender_kb
            db.set_state(uid, config.ST_REG_GENDER, ctx)
            await q.answer()
            await q.message.reply_text(
                "🚻 جنسیت جدید را انتخاب کن:", reply_markup=gender_kb())
            return
        if field == "city":
            # استان با کیبورد Reply انتخاب می‌شود؛ با تغییر استان، شهر قبلی پاک می‌شود
            from keyboards import provinces_reply_kb
            db.set_state(uid, config.ST_REG_PROVINCE, ctx)
            await q.answer()
            await q.message.reply_text(
                "🏙 استان جدید را انتخاب کن:\n"
                "(اگر استان را عوض کنی، شهر قبلی پاک می‌شود و شهر جدید را انتخاب می‌کنی)",
                reply_markup=provinces_reply_kb())
            return
        prompts = {
            "nickname": ("✏️ اسم جدید را بنویس:", config.ST_REG_NICKNAME),
            "age": ("🎂 سن جدید را انتخاب کن:", config.ST_REG_AGE),
        }
        prompt, st = prompts.get(field, (None, None))
        if not prompt:
            await q.answer()
            return
        db.set_state(uid, st, ctx)
        await q.answer()
        if st == config.ST_REG_AGE:
            from keyboards import age_kb
            await q.message.reply_text(prompt, reply_markup=age_kb())
        else:
            await q.message.reply_text(prompt, reply_markup=remove_kb)
        return

    if data == "coins:tips":
        await q.answer()
        reward = S.get_int("referral_reward")
        await q.message.reply_text(
            "🪙 <b>راه‌های گرفتن سکه:</b>\n\n"
            f"1. 🎁 دعوت دوستان با لینک اختصاصی: {reward} سکه برای هر نفر\n"
            "2. 🪙 سکه خوش‌آمدگویی هنگام ثبت‌نام\n"
            "3. 🟢 چت تصادفی همیشه رایگان است!",
            parse_mode="HTML")
        return

    await q.answer()


async def show_profile_cb(q, uid: int) -> None:
    user = db.get_user(uid)
    card = H.user_card(user, show_coins=True)
    try:
        if user["avatar_file_id"]:
            await q.message.reply_photo(photo=user["avatar_file_id"], caption=card,
                                        parse_mode="HTML",
                                        reply_markup=profile_kb(True))
            return
    except Exception:
        pass
    await q.message.reply_text(card, parse_mode="HTML", reply_markup=profile_kb(False))
