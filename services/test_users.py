"""مدیریت کاربران تستی: ساخت انبوه، انتخاب شریک تطبیق، مدیریت تست‌مود."""
import json
import logging
import random
from datetime import datetime, timedelta, timezone

import config
import database as db
from services import settings as S

log = logging.getLogger("bagoodit.test")

TEST_BOT_ID_BASE = 900000000  # telegram_id مصنفی: -900000001 و بعدتر

F_NAMES = ["نگار", "سارا", "مریم", "زهرا", "الناز", "نیلوفر", "مهسا", "درسا",
           "پریسا", "رها", "آوا", "یاسمن", "ستایش", "مبینا", "هستی", "غزاله",
           "کیمیا", "ترانه", "شیرین", "لیلا", "آیدا", "بهار", "سپیده", "شیوا",
           "نورا", "تارا", "مهتاب", "آیناز", "پوپک", "نازنین", "عسل", "دلارام",
           "مینا", "رویا", "سمانه", "فرزانه", "الهام", "شقایق", "ونداد", "لینا"]
M_NAMES = ["امیر", "رضا", "علی", "محمد", "مهدی", "آرش", "سامان", "بهنام", "کیان",
           "آرمان", "پویا", "سینا", "فرهاد", "بابک", "ایمان", "حسام", "میلاد",
           "رامین", "سعید", "وحید", "نیما", "آریا", "بهزاد", "شهرام", "کاوه",
           "دانیال", "مسعود", "حمید", "شهریار", "فرزین", "هومن", "سعیدرضا",
           "پارسا", "ابوالفضل", "ماکان", "یاشار", "بردیا", "کوروش", "سروش", "ثمین"]

HOBBIES = ["موسیقی", "فیلم و سریال", "کتاب‌خوانی", "آشپزی", "ورزش", "بازی",
           "کوهنوردی", "عکاسی", "نقاشی", "سفر"]


def _nickname(gender: str, i: int) -> str:
    """نام مستعار فارسی — بدون هیچ حرف لاتین یا عدد (هم‌راستا با قانون نام فارسی)."""
    rng = random.Random(f"nick-{gender}-{i}")
    base = rng.choice(F_NAMES if gender == "F" else M_NAMES)
    suffix = rng.choice(["", "", "", "", f"‌{rng.choice(HOBBIES)}",
                         f" {rng.choice(HOBBIES)}"])
    nick = f"{base}{suffix}"
    return nick[:30]


def generate_test_users(force=False) -> int:
    """ساخت کاربران تستی برای هر شهر (ظرفیت‌ها از تنظیمات ادمین) — idempotent و ضدتصادم."""
    import locations
    f_per_city = S.get_int("test_users_per_city_f")
    m_per_city = S.get_int("test_users_per_city_m")
    existing = db.q1("SELECT COUNT(*) AS c FROM users WHERE is_test_user=1")["c"]
    if existing > 0 and not force:
        return 0
    idx = db.q1("SELECT COALESCE(MAX(ABS(telegram_id)),0) AS m FROM users "
                "WHERE telegram_id<0")["m"]
    used_bot_ids = {r["bot_user_id"] for r in db.q(
        "SELECT bot_user_id FROM users WHERE bot_user_id IS NOT NULL")}
    counter = 0
    inserted = 0
    rows = []

    def _new_bot_id(g):
        lo, hi = (50000, 59999) if g == "F" else (40000, 49999)
        while True:
            n = random.randint(lo, hi)
            bot_id = f"user{n}"
            if bot_id not in used_bot_ids:
                used_bot_ids.add(bot_id)
                return bot_id

    def _flush():
        nonlocal inserted
        if rows:
            with db._lock:
                db._conn.executemany(
                    "INSERT INTO users (telegram_id, bot_user_id, nickname, gender, age, "
                    "province, city, coins, state, context, banned, is_test_user, referred_by, "
                    "created_at, last_active) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
                db._conn.commit()
            inserted += len(rows)
            rows.clear()

    for pidx, (prov, cities) in enumerate(locations.PROVINCES):
        for cidx, city in enumerate(cities):
            for g, count in (("F", f_per_city), ("M", m_per_city)):
                for _ in range(count):
                    idx += 1
                    counter += 1
                    tid = -(TEST_BOT_ID_BASE + idx)
                    nick = _nickname(g, counter)
                    bot_id = _new_bot_id(g)
                    age = random.randint(config.AGE_MIN, config.AGE_MAX)
                    rows.append((tid, bot_id, nick, g, age, prov, city, 0, "NONE",
                                 "{}", 0, 1, None, db.now_iso(), db.now_iso()))
                    if len(rows) >= 1000:
                        _flush()
    _flush()
    log.info("seeded %s test users", inserted)
    return inserted


def test_mode_active() -> bool:
    if S.get("test_mode_manually_disabled").strip().lower() == "true":
        return False
    if S.get("test_mode_enabled").strip().lower() != "true":
        return False
    exp = (S.get("test_mode_expires_at") or "").strip()
    if exp and datetime.now(timezone.utc).isoformat(timespec="seconds") > exp:
        return False
    return True


def start_test_mode(days: int) -> None:
    now = datetime.now(timezone.utc)
    S.set_value("test_mode_enabled", "true")
    S.set_value("test_mode_manually_disabled", "false")
    S.set_value("test_mode_started_at", now.isoformat(timespec="seconds"))
    S.set_value("test_mode_expires_at",
                (now + timedelta(days=days)).isoformat(timespec="seconds"))


def stop_test_mode(manual=True) -> None:
    S.set_value("test_mode_enabled", "false")
    if manual:
        S.set_value("test_mode_manually_disabled", "true")


def enforce_test_mode(context=None) -> bool:
    """هر بار تطبیق بررسی می‌شود؛ اگر منقضی باشد خاموش + اطلاع به ادمین."""
    if S.get("test_mode_enabled").strip().lower() != "true":
        return False
    exp = (S.get("test_mode_expires_at") or "").strip()
    if not exp:
        return True
    if datetime.now(timezone.utc).isoformat(timespec="seconds") <= exp:
        return True
    S.set_value("test_mode_enabled", "false")
    log.info("test mode expired")
    if context is not None and config.ADMIN_ID:
        import asyncio
        try:
            asyncio.get_running_loop().create_task(_notify_admin_expired(context))
        except RuntimeError:
            pass
    return False


async def _notify_admin_expired(context) -> None:
    from utils import helpers
    await helpers.notify(context.bot, config.ADMIN_ID,
                         "⏰ <b>تست‌مود بگودیت منقضی شد.</b>\nکاربران تستی دیگر وارد تطبیق نمی‌شوند.\nبرای تمدید: /admin → 🧪 کاربران تستی")


def pick_test_partner(gender=None, city=None, province=None,
                      min_age=None, max_age=None, exclude=None):
    """انتخاب تصادفی کاربر تستی آزاد منطبق با شرایط جست‌وجو."""
    exclude = set(exclude or [])
    sql = ("SELECT * FROM users WHERE is_test_user=1 AND state!='IN_CHAT' "
           "AND banned=0")
    params = []
    if gender:
        sql += " AND gender=?"
        params.append(gender)
    if city:
        sql += " AND city=?"
        params.append(city)
    elif province:
        sql += " AND province=?"
        params.append(province)
    if min_age:
        sql += " AND age>=?"
        params.append(int(min_age))
    if max_age:
        sql += " AND age<=?"
        params.append(int(max_age))
    sql += " ORDER BY RANDOM() LIMIT 50"
    rows = db.q(sql, params)
    rows = [r for r in rows if r["telegram_id"] not in exclude]
    return random.choice(rows) if rows else None


def gender_for_kind(kind: str):
    """جنسیت مورد انتظار شریک بر اساس نوع جست‌وجو."""
    if kind == "girl":
        return "F"
    if kind == "boy":
        return "M"
    return None


def test_counts() -> dict:
    total = db.q1("SELECT COUNT(*) AS c FROM users WHERE is_test_user=1")["c"]
    f = db.q1("SELECT COUNT(*) AS c FROM users WHERE is_test_user=1 AND gender='F'")["c"]
    return {"total": total, "female": f, "male": total - f}


def pool_from_settings() -> list:
    raw = db.get_setting("avatar_pool")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return []
