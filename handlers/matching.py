"""منوی تطبیق، صف انتظار، ویزارد جست‌وجوی پیشرفته و لغو جست‌وجو."""
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

import config
import database as db
from keyboards import (BTN_BACK, BTN_CANCEL_SEARCH, BTN_MATCH_BOY,
                       BTN_MATCH_FILTER, BTN_MATCH_GIRL, BTN_MATCH_NEARBY,
                       BTN_MATCH_RANDOM, cities_kb, main_menu_kb,
                       match_menu_kb, provinces_kb, remove_kb)
from services import matching

log = logging.getLogger("bagoodit.match")


# ---------------- منوی تطبیق ----------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      user: dict) -> None:
    uid = user["telegram_id"]
    text = (update.message.text or "").strip()

    if text == BTN_BACK:
        db.set_state(uid, config.ST_MAIN)
        await update.message.reply_text("منوی اصلی:", reply_markup=main_menu_kb())
        return

    if text == BTN_MATCH_RANDOM:
        await matching.start_search(context, uid, "random")
        return
    if text == BTN_MATCH_GIRL:
        await matching.start_search(context, uid, "girl")
        return
    if text == BTN_MATCH_BOY:
        await matching.start_search(context, uid, "boy")
        return
    if text == BTN_MATCH_NEARBY:
        await matching.start_search(context, uid, "nearby")
        return
    if text == BTN_MATCH_FILTER:
        db.set_state(uid, config.ST_FILTER, {"fw": {"step": "min"}})
        await update.message.reply_text(
            "🟣 <b>جست‌وجوی پیشرفته</b>\n\nحداقل سن را بنویس (۱۸ تا ۷۹):",
            parse_mode="HTML", reply_markup=remove_kb)
        return

    await update.message.reply_text("از دکمه‌های منو استفاده کن 👇",
                                    reply_markup=match_menu_kb())


# ---------------- صف انتظار ----------------
async def handle_searching_text(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                user: dict) -> None:
    text = (update.message.text or "").strip()
    if text == BTN_CANCEL_SEARCH:
        await matching.cancel_search(context, user["telegram_id"])
        return
    await update.message.reply_text("در صف انتظار هستی؛ فقط «❌ لغو جستجو» فعال است.")


# ---------------- ویزارد جست‌وجوی پیشرفته ----------------
async def handle_filter_text(update: Update, context: ContextTypes.DEFAULT_TYPE,
                             user: dict) -> None:
    uid = user["telegram_id"]
    ctx = db.get_ctx(user)
    fw = ctx.get("fw") or {}
    text = (update.message.text or "").strip()

    if fw.get("step") == "min":
        if not re.fullmatch(r"\d{1,2}", text):
            await update.message.reply_text("فقط عدد بنویس (۱۸ تا ۷۹):")
            return
        v = int(text)
        if not (config.AGE_MIN <= v <= config.AGE_MAX):
            await update.message.reply_text("بین ۱۸ تا ۷۹ بگو:")
            return
        fw["step"] = "max"
        fw["min"] = v
        db.set_state(uid, config.ST_FILTER, {"fw": fw})
        await update.message.reply_text("حداکثر سن را بنویس:")
        return

    if fw.get("step") == "max":
        if not re.fullmatch(r"\d{1,2}", text):
            await update.message.reply_text("فقط عدد بنویس (۱۸ تا ۷۹):")
            return
        v = int(text)
        if not (config.AGE_MIN <= v <= config.AGE_MAX) or v < fw.get("min", config.AGE_MIN):
            await update.message.reply_text(
                f"حداکثر باید بین حداقل ({fw.get('min')}) و ۷۹ باشد:")
            return
        fw["step"] = "city"
        fw["max"] = v
        db.set_state(uid, config.ST_FILTER, {"fw": fw})
        await update.message.reply_text("🗺 استان مورد نظر را انتخاب کن:")
        await update.message.reply_text("استان:", reply_markup=provinces_kb(0, prefix="fw"))
        return

    await update.message.reply_text("ویزارد نیمه‌کاره شد؛ /cancel را بزن.")


# ---------------- callbackهای ویزارد (fw:) ----------------
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict) -> None:
    q = update.callback_query
    data = q.data or ""
    uid = user["telegram_id"]
    ctx = db.get_ctx(user)
    fw = ctx.get("fw") or {}
    parts = data.split(":")
    if parts[0] != "fw":
        await q.answer()
        return

    if parts[1] == "page" and len(parts) == 3:
        await q.answer()
        await q.message.edit_reply_markup(reply_markup=provinces_kb(int(parts[2]), prefix="fw"))
        return

    if parts[1] == "cpage" and len(parts) == 4:
        await q.answer()
        await q.message.edit_reply_markup(
            reply_markup=cities_kb(int(parts[2]), int(parts[3]), prefix="fw"))
        return

    if parts[1] == "back":
        await q.answer()
        await q.message.edit_reply_markup(reply_markup=provinces_kb(0, prefix="fw"))
        return

    if parts[1] == "prov" and len(parts) == 3:
        fw["pidx"] = int(parts[2])
        db.set_state(uid, config.ST_FILTER, {"fw": fw})
        await q.answer()
        await q.message.edit_reply_markup(
            reply_markup=cities_kb(int(parts[2]), 0, prefix="fw"))
        return

    if parts[1] == "city" and len(parts) == 4:
        import locations
        res = locations.city_by_indices(int(parts[2]), int(parts[3]))
        if not res:
            await q.answer("نامعتبر!")
            return
        prov, city = res
        if fw.get("step") != "city" or "min" not in fw:
            await q.answer("خطای ویزارد!")
            return
        extra = (fw.get("min"), fw.get("max"), city, prov)
        db.set_state(uid, config.ST_MATCH_MENU, {})
        await q.answer()
        await q.message.reply_text(f"🔎 در حال جست‌وجو: سن {fw.get('min')}-{fw.get('max')} در {city}…")
        await matching.start_search(context, uid, "filter", extra)
        return

    await q.answer()
