"""ثبت‌نام مرحله‌به‌مرحله + ویرایش پروفایل (با همان مراحل).
انتخاب استان و شهر با کیبورد Reply واقعی تلگرام انجام می‌شود؛
منطق مشترک در _province_chosen/_city_chosen متمرکز است."""
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

import config
import database as db
import locations
from keyboards import (BTN_PROV_BACK, BTN_SKIP_PHOTO, age_kb, cities_reply_kb,
                       gender_kb, main_menu_kb, provinces_reply_kb, remove_kb,
                       skip_photo_kb)
from services import coins
from services import settings as S
from utils import helpers as H

log = logging.getLogger("bagoodit.reg")

_TEXT_ONLY = "این مرحله با دکمه‌ها انتخاب می‌شود؛ متن نفرست."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict,
                args: list) -> None:
    uid = user["telegram_id"]

    # ---- پیوند معرفی (Referral) ----
    if args:
        payload = args[0].strip()
        m = re.fullmatch(r"ref(\d+)", payload, re.IGNORECASE)
        if m and not user.get("referred_by"):
            referrer_tid = int(m.group(1))
            if referrer_tid != uid and not user["is_test_user"]:
                if db.bind_referral(uid, referrer_tid):
                    reward = S.get_int("referral_reward")
                    coins.earn(referrer_tid, reward, "referral")
                    cnt = db.referral_count(referrer_tid)
                    from services import notifications as NF
                    NF.ev_referral(referrer_tid, reward, cnt, uid)
                    await H.notify(
                        context.bot, referrer_tid,
                        f"🎁 <b>یک دوست با لینک تو به بگودیت اومد!</b>\n"
                        f"🪙 {reward} سکه به موجودی‌ات اضافه شد.\n"
                        f"📈 مجموع دعوت‌های موفق: {cnt}")

    if user["banned"]:
        await update.message.reply_text(
            "🚫 <b>دسترسی شما مسدود شده است.</b>", parse_mode="HTML")
        return

    if db.is_registered(user):
        db.set_state(uid, config.ST_MAIN)
        await update.message.reply_text(
            "👋 <b>سلام! دوباره برگشتی.</b>\nاز منوی زیر استفاده کن:",
            parse_mode="HTML", reply_markup=main_menu_kb())
        return

    # شروع ثبت‌نام
    db.set_state(uid, config.ST_REG_GENDER, {})
    await update.message.reply_text(
        "👋 <b>به بگودیت خوش اومدی!</b>\n\n"
        "🔐 اینجا کاملاً ناشناس هستی؛ اسم واقعی و آیدی تو هیچ‌وقت نشان داده نمی‌شود.\n"
        "۱️⃣ قدم اول — جنسیتت را انتخاب کن:",
        parse_mode="HTML", reply_markup=gender_kb())


# ---------------- پیام‌های متنی در حالت ثبت‌نام ----------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      user: dict) -> None:
    uid = user["telegram_id"]
    state = user["state"]
    ctx = db.get_ctx(user)
    text = (update.message.text or "").strip()

    if state == config.ST_REG_AGE:
        if not re.fullmatch(r"\d{1,2}", text):
            await update.message.reply_text("لطفاً فقط سن را به‌صورت عدد انتخاب کن.")
            return
        age = int(text)
        if not (config.AGE_MIN <= age <= config.AGE_MAX):
            await update.message.reply_text(
                f"فقط سن بین {config.AGE_MIN} تا {config.AGE_MAX} قابل قبول است.")
            return
        db.update_user(uid, age=age)
        if ctx.get("edit") == "age":
            await _finish_edit(update, context, uid)
            return
        db.set_state(uid, config.ST_REG_PROVINCE, {})
        await update.message.reply_text(
            "۲️⃣ استان محل سکونتت را انتخاب کن:",
            reply_markup=provinces_reply_kb())
        return

    if state == config.ST_REG_PROVINCE:
        prov = locations.province_by_name(text)
        if not prov:
            await update.message.reply_text(
                "⚠️ استان نامعتبر است؛ لطفاً فقط از دکمه‌های زیر استانت را انتخاب کن:",
                reply_markup=provinces_reply_kb())
            return
        await _province_chosen(update, context, user, ctx, prov)
        return

    if state == config.ST_REG_CITY:
        if text == BTN_PROV_BACK:
            ctx.pop("prov", None)
            db.set_state(uid, config.ST_REG_PROVINCE, ctx)
            await update.message.reply_text(
                "🗺 استان را دوباره انتخاب کن:", reply_markup=provinces_reply_kb())
            return
        prov = (ctx.get("prov") or "").strip()
        if not prov:
            # کانتکست گم شده (مثلاً قطع‌وشدن وسط کار) → از مرحله استان شروع کن
            db.set_state(uid, config.ST_REG_PROVINCE, {})
            await update.message.reply_text(
                "🗺 اول استانت را انتخاب کن:", reply_markup=provinces_reply_kb())
            return
        city = locations.city_in_province(prov, text)
        if not city:
            # ضربه سریع روی دکمه استان (هم‌زمان با تعویض کیبورد): اگر متن
            # نام معتبر «استان» باشد، به‌عنوان تعویض استان پردازش می‌شود؛
            # اولویت با شهرهای همان استان است تا اسم‌های مشترک مثل «قم» سالم بمانند.
            new_prov = locations.province_by_name(text)
            if new_prov:
                await _province_chosen(update, context, user, ctx, new_prov)
                return
            await update.message.reply_text(
                "⚠️ شهر نامعتبر است؛ لطفاً فقط یکی از شهرهای استان "
                f"«{prov}» را از دکمه‌های زیر انتخاب کن:",
                reply_markup=cities_reply_kb(prov))
            return
        await _city_chosen(update, context, uid, prov, city)
        return

    if state == config.ST_REG_NICKNAME:
        nick = text.strip()
        if not (config.NICK_MIN <= len(nick) <= config.NICK_MAX):
            await update.message.reply_text(
                f"اسم باید بین {config.NICK_MIN} تا {config.NICK_MAX} کاراکتر باشد.")
            return
        db.update_user(uid, nickname=nick)
        if ctx.get("edit") == "nickname":
            await _finish_edit(update, context, uid)
            return
        db.set_state(uid, config.ST_REG_PHOTO, {})
        await update.message.reply_text(
            "🖼 قدم آخر — یک عکس برای پروفایلت بفرست (گرافیکی/کاریکاتور بهتر است؛ "
            "عکس واقعی‌ات نمایش داده نمی‌شود مگر خودت بخواهی).\n"
            "اگر عکس نداری، «⏭ رد کردن عکس» را بزن.",
            reply_markup=skip_photo_kb())
        return

    if state == config.ST_REG_PHOTO:
        if text == BTN_SKIP_PHOTO:
            await _complete(update, context, uid)
            return
        await update.message.reply_text("عکس را بفرست یا «⏭ رد کردن عکس» را بزن.")
        return

    # حالت‌های دکمه‌ای
    await update.message.reply_text(_TEXT_ONLY)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       user: dict) -> None:
    uid = user["telegram_id"]
    ctx = db.get_ctx(user)
    photo = update.message.photo
    if not photo:
        await update.message.reply_text("فقط عکس قابل قبول است.")
        return
    file_id = photo[-1].file_id
    db.update_user(uid, avatar_file_id=file_id)
    if ctx.get("edit") == "photo":
        await _finish_edit(update, context, uid)
        return
    await _complete(update, context, uid)


# ---------------- منطق مشترک انتخاب استان/شهر (متن یا دکمه قدیمی) ----------------
async def _province_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           user: dict, ctx: dict, prov: str) -> None:
    """پس از انتخاب استان معتبر: ذخیره وضعیت، پاک‌شدن شهر قبلی در صورت تغییر استان،
    و نمایش شهرهای همان استان با کیبورد Reply."""
    uid = user["telegram_id"]
    old_prov = (user.get("province") or "").strip()
    if old_prov and old_prov != prov:
        # تغییر استان → شهر قبلی باطل می‌شود تا کاربر دوباره شهر را انتخاب کند
        db.update_user(uid, province=prov, city=None)
    ctx = dict(ctx or {})
    ctx["prov"] = prov
    db.set_state(uid, config.ST_REG_CITY, ctx)
    await update.effective_message.reply_text(
        f"✅ استان «{prov}» ثبت شد.\n🏙 حالا شهرت را انتخاب کن:",
        reply_markup=cities_reply_kb(prov))


async def _city_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       uid: int, prov: str, city: str) -> None:
    """پس از انتخاب شهر معتبرِ همان استان: ذخیره در دیتابیس و رفتن به مرحله بعد."""
    db.update_user(uid, province=prov, city=city)
    ctx = db.get_ctx(db.get_user(uid))
    if ctx.get("edit") == "city":
        await _finish_edit(update, context, uid)
        return
    db.set_state(uid, config.ST_REG_NICKNAME, {})
    await update.effective_message.reply_text(
        "۳️⃣ یک اسم مستعار (NickName) برای خودت انتخاب کن:\n"
        f"• بین {config.NICK_MIN} تا {config.NICK_MAX} کاراکتر\n"
        "• بدون نام واقعی؛ هر چیزی که دوست داری",
        reply_markup=remove_kb)


# ---------------- callbackهای دکمه‌ای ----------------
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict) -> None:
    q = update.callback_query
    data = q.data or ""
    uid = q.from_user.id
    ctx = db.get_ctx(user)

    # فقط callbackهای reg: اینجا هندل می‌شوند؛ ویزارد fw: در matching است.
    # دکمه‌های قدیمی اینلاین (قبل از مهاجرت به Reply) هم با همان منطق مشترک کار می‌کنند.
    if not data.startswith("reg:"):
        await q.answer()
        return

    parts = data.split(":")

    if parts[1] == "gender" and len(parts) == 3 and parts[2] in ("F", "M"):
        db.update_user(uid, gender=parts[2])
        await q.answer()
        if ctx.get("edit") == "gender":
            await _finish_edit(update, context, uid)
            return
        db.set_state(uid, config.ST_REG_AGE, {})
        await q.message.reply_text("۲️⃣ سنت را انتخاب کن:", reply_markup=age_kb())
        return

    if parts[1] == "page" and len(parts) == 3 and parts[2].isdigit():
        await q.answer("این دکمه قدیمی است؛ از کیبورد پایین صفحه استفاده کن.")
        return

    if parts[1] == "cpage" and len(parts) == 4 and parts[2].isdigit() and parts[3].isdigit():
        await q.answer("این دکمه قدیمی است؛ از کیبورد پایین صفحه استفاده کن.")
        return

    if parts[1] == "back":
        await q.answer("این دکمه قدیمی است؛ از کیبورد پایین صفحه استفاده کن.")
        return

    # دکمه‌های قدیمی اینلاین استان/شهر (پیام‌های قبل از مهاجرت به Reply Keyboard)
    # همچنان کار می‌کنند، اما فقط اگر کاربر واقعاً در همان مرحله باشد؛
    # منطق انتخاب دقیقاً همان مسیر متنی مشترک است.
    if parts[1] == "prov" and len(parts) == 3 and parts[2].isdigit():
        p = locations.province_by_index(int(parts[2]))
        if user["state"] not in (config.ST_REG_PROVINCE, config.ST_REG_CITY) or not p:
            await q.answer("این دکمه قدیمی است؛ استان را از کیبورد پایین صفحه انتخاب کن.")
            return
        await q.answer()
        await _province_chosen(update, context, user, ctx, p[0])
        return

    if parts[1] == "city" and len(parts) == 4 and parts[2].isdigit() and parts[3].isdigit():
        res = locations.city_by_indices(int(parts[2]), int(parts[3]))
        if user["state"] != config.ST_REG_CITY or not res:
            await q.answer("این دکمه قدیمی است؛ شهر را از کیبورد پایین صفحه انتخاب کن.")
            return
        await q.answer()
        await _city_chosen(update, context, uid, res[0], res[1])
        return

    await q.answer()


# ---------------- تکمیل و ویرایش ----------------
async def _complete(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int) -> None:
    user = db.get_user(uid)
    gender = user["gender"]
    if not user["bot_user_id"]:
        db.update_user(uid, bot_user_id=db.gen_bot_user_id(gender))
    user = db.get_user(uid)
    db.set_state(uid, config.ST_MAIN)
    await update.effective_message.reply_text(
        "✅ <b>ثبت‌نام کامل شد!</b>\n\n"
        f"🆔 شناسه ناشناس تو: <code>{H.esc(user['bot_user_id'])}</code>\n"
        "این شناسه را فقط به کسانی بده که می‌خواهی پیدا کنندت.\n"
        f"🪙 موجودی اولیه: {user['coins']} سکه",
        parse_mode="HTML", reply_markup=main_menu_kb())
    await update.effective_message.reply_text(
        "💬 «چت ناشناس» را بزن تا شروع کنیم!",
        reply_markup=main_menu_kb())


async def _finish_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int) -> None:
    db.set_state(uid, config.ST_MAIN, {})
    from handlers import main_menu
    await main_menu.show_profile(update, context, uid)
