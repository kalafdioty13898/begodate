"""موتور تطبیق: صف انتظار، سازگاری دوطرفه، اولویت کاربر واقعی، جلوگیری از تکرار."""
import random

import config
import database as db
from services import coins
from services import settings as S
from services import test_users
from utils import helpers as H

KIND_COST_KEY = {
    "random": None,          # همیشه رایگان
    "girl": "coin_girl",
    "boy": "coin_boy",
    "nearby": "coin_nearby",
    "filter": "coin_filter",
}

KIND_LABEL = {
    "random": "🟢 چت تصادفی",
    "girl": "🔵 جست‌وجوی دختر",
    "boy": "🔵 جست‌وجوی پسر",
    "nearby": "🔴 افراد نزدیک",
    "filter": "🟣 جست‌وجوی پیشرفته",
    "request": "💬 درخواست مستقیم",
}


def cost_of(kind: str) -> int:
    key = KIND_COST_KEY.get(kind)
    return S.get_int(key) if key else config.COIN_COST_RANDOM


def build_criteria(kind: str, extra=None) -> dict:
    c = {"kind": kind, "min_age": None, "max_age": None, "city": None,
         "province": None}
    if kind == "filter" and extra:
        c["min_age"], c["max_age"], c["city"], c["province"] = extra
    return c


def criteria_from_ctx(ctx: dict) -> dict:
    s = (ctx or {}).get("search")
    return s if isinstance(s, dict) else {"kind": "random", "min_age": None,
                                          "max_age": None, "city": None,
                                          "province": None}


def _profile_ok(u) -> bool:
    return bool(u and u.get("nickname") and u.get("gender") and u.get("age")
                and u.get("province") and u.get("city"))


def _one_way_ok(searcher: dict, criteria: dict, target: dict) -> bool:
    """آیا «searcher» با شرایطش، «target» را قبول می‌کند؟"""
    if not _profile_ok(target) or target.get("banned"):
        return False
    k = criteria.get("kind")
    if k == "girl" and target.get("gender") != "F":
        return False
    if k == "boy" and target.get("gender") != "M":
        return False
    if k == "nearby":
        if (target.get("city") != searcher.get("city")
                and target.get("province") != searcher.get("province")):
            return False
    if k == "filter":
        if criteria.get("min_age") and (target.get("age") or 0) < criteria["min_age"]:
            return False
        if criteria.get("max_age") and (target.get("age") or 0) > criteria["max_age"]:
            return False
        if criteria.get("city") and target.get("city") != criteria["city"]:
            return False
    return True


def pair_compatible(u1: dict, c1: dict, u2: dict, c2: dict) -> bool:
    return (_one_way_ok(u1, c1, u2) and _one_way_ok(u2, c2, u1)
            and u1["telegram_id"] != u2["telegram_id"])


def find_real_partner(searcher: dict, criteria: dict):
    """بهترین شریک واقعی در صف؛ امتیاز نزدیکی + تصادفی بین برابرها."""
    cooldown = S.get_int("match_cooldown_minutes")
    candidates = []
    for row in db.list_state(config.ST_SEARCHING):
        tid = row["telegram_id"]
        if tid == searcher["telegram_id"] or row["banned"]:
            continue
        if not _profile_ok(row):
            continue
        pc = criteria_from_ctx(db.get_ctx(row))
        if not pair_compatible(searcher, criteria, row, pc):
            continue
        if db.was_recently_matched(searcher["telegram_id"], tid, cooldown):
            continue
        score = 0
        if criteria["kind"] == "nearby":
            if row["city"] == searcher["city"]:
                score += 2
            elif row["province"] == searcher["province"]:
                score += 1
        if pc["kind"] == "nearby":
            if searcher["city"] == row["city"]:
                score += 2
            elif searcher["province"] == row["province"]:
                score += 1
        candidates.append((score, row))
    if not candidates:
        return None
    top = max(c for c, _ in candidates)
    best = [r for c, r in candidates if c == top]
    return random.choice(best)


def find_test_partner(searcher: dict, criteria: dict):
    if not test_users.test_mode_active():
        return None
    return test_users.pick_test_partner(
        gender=test_users.gender_for_kind(criteria["kind"]),
        city=searcher["city"] if criteria["kind"] == "nearby" else criteria.get("city"),
        province=searcher["province"] if criteria["kind"] == "nearby" else None,
        min_age=criteria.get("min_age"), max_age=criteria.get("max_age"))


def partner_brief(partner: dict, reveal_city=False, is_test=False) -> str:
    lines = ["🎉 <b>چت ناشناس برقرار شد!</b>", ""]
    lines.append(f"👤 جنسیت طرف مقابل: {H.gender_label(partner['gender'])}")
    lines.append(f"🎂 سن: {partner['age']}")
    if reveal_city and partner.get("city"):
        lines.append(f"📍 {H.esc(partner['city'])}")
    if is_test:
        lines.append("🧪 <i>این حساب تستی بگودیت است (کاربر واقعی نیست).</i>")
    lines.append("")
    lines.append("💬 از همین‌جا پیام بفرست؛ از دکمه‌های زیر هم استفاده کن.")
    return "\n".join(lines)


async def start_search(context, uid: int, kind: str, extra=None) -> None:
    """شروع جست‌وجو با همه چک‌های امنیتی و اقتصادی."""
    bot = context.bot
    user = db.get_user(uid)
    if not user or user["banned"]:
        await H.notify(bot, uid, "🚫 دسترسی شما مسدود است.")
        return
    if not db.is_registered(user):
        await H.notify(bot, uid, "اول ثبت‌نام را کامل کن؛ /start را بزن.")
        return
    active = db.get_active_chat(uid)
    if active:
        await H.notify(bot, uid, "شما در چت دیگری هستید؛ اول آن را پایان بده.")
        return
    if user["state"] == config.ST_SEARCHING:
        await H.notify(bot, uid, "شما در صف انتظار هستید؛ ⬅️ لغو جستجو یا بزن.")
        return

    # بررسی انقضای تست‌مود — «هر بار» در لحظه تطبیق
    test_users.enforce_test_mode(context)

    cost = cost_of(kind)
    if cost > 0:
        ok, bal = coins.spend(uid, cost, f"search:{kind}")
        if not ok:
            await H.notify(bot, uid,
                           "🪙 <b>سکه کافی نداری.</b>\nبا 🎁 دعوت دوستان سکه جمع کن.")
            return

    criteria = build_criteria(kind, extra)
    partner = None
    is_test = False
    real_first = S.get_bool("real_users_first")

    real_p = find_real_partner(user, criteria)
    test_p = find_test_partner(user, criteria) if real_p is None or not real_first else None
    if not real_first and test_p is not None:
        partner, is_test = test_p, True
    elif real_p is not None:
        partner = real_p
    elif test_p is not None:
        partner, is_test = test_p, True

    if partner is not None:
        cap = random.randint(6, max(6, S.get_int("test_user_max_replies"))) if is_test else None
        cid = db.pair_users(uid, partner["telegram_id"], kind, b_is_test=is_test,
                            test_replies_cap=cap)
        if cid is None:
            coins.refund(uid, cost, kind)
            await H.notify(bot, uid, "⏳ لحظه‌ای همه‌چیز پر شد؛ دوباره امتحان کن.")
            return
        # اطلاع‌رسانی به دو طرف
        reveal_city = kind in ("nearby", "filter")
        from keyboards import chat_kb
        await H.notify(bot, uid, partner_brief(partner, reveal_city, is_test),
                       reply_markup=chat_kb())
        if not is_test:
            from keyboards import chat_kb as _ck
            await H.notify(bot, partner["telegram_id"],
                           partner_brief(user, reveal_city, False),
                           reply_markup=_ck())
        else:
            # پیام اول از طرف کاربر تستی + شمارنده
            from services import auto_reply
            db.bump_test_reply(cid)
            db.set_last_reply(cid, "")
            delay = random.uniform(S.get_float("test_reply_min_delay"),
                                   S.get_float("test_reply_max_delay"))
            context.job_queue.run_once(
                auto_reply.greeting_job, when=delay,
                data={"chat_id": cid, "test_uid": partner["telegram_id"],
                      "real_uid": uid}, name=f"tgreet:{cid}")
        return

    # هیچ شریکی نیست → صف انتظار
    db.set_state(uid, config.ST_SEARCHING,
                 {"search": criteria, "joined": db.now_iso()})
    cost_line = f"\n🪙 {cost} سکه بابت این جست‌وجو کم شد (لغو = بازگشت سکه)." if cost else ""
    await H.notify(
        bot, uid,
        "📡 <b>وارد صف انتظار شدی...</b>\n"
        "به‌محض پیدا شدن شخص مناسب، چت برقرار می‌شود." + cost_line +
        "\n\nبرای انصراف دکمه «❌ لغو جستجو» را بزن.",
        reply_markup=searching_kb_inline())


def searching_kb_inline():
    from telegram import ReplyKeyboardMarkup
    return ReplyKeyboardMarkup([["❌ لغو جستجو"]], resize_keyboard=True,
                               input_field_placeholder="در صف انتظار...")


async def cancel_search(context, uid: int) -> bool:
    user = db.get_user(uid)
    if not user or user["state"] != config.ST_SEARCHING:
        return False
    criteria = criteria_from_ctx(db.get_ctx(user))
    cost = cost_of(criteria.get("kind", "random"))
    if cost > 0:
        coins.refund(uid, cost, criteria.get("kind", "random"))
    db.set_state(uid, config.ST_MAIN)
    from keyboards import main_menu_kb
    refund_note = f"\n🪙 {cost} سکه به موجودی‌ات برگشت." if cost else ""
    await H.notify(context.bot, uid,
                   "❌ جست‌وجو لغو شد." + refund_note,
                   reply_markup=main_menu_kb())
    return True


async def notify_forced_close(context, uid: int, reason: str) -> None:
    from keyboards import main_menu_kb
    await H.notify(context.bot, uid, reason, reply_markup=main_menu_kb())
