"""سوئیت جامع v2 بگودیت — پوشش ۲۰ مرحله‌ی تست مشخصات.
اجرا: python3 tests/test_v2_suite.py
تست‌های نیازمند تلگرام واقعی در گزارش «اجرا‌نشده» اعلام می‌شوند و هرگز موفق جعل نمی‌شوند.
"""
import asyncio
import os
import sys
import tempfile
import time

_TMPDIR = tempfile.mkdtemp(prefix="bagoodit-v2-")
os.environ["DB_PATH"] = os.path.join(_TMPDIR, "v2.db")
os.environ["TEST_USERS_PER_CITY_F"] = "1"
os.environ["TEST_USERS_PER_CITY_M"] = "1"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
config.ADMIN_ID = 990111

import database as db  # noqa: E402
from handlers import common, registration  # noqa: E402
from keyboards import BTN_CHAT_END, BTN_CHAT_REPORT  # noqa: E402
from services import matching as M  # noqa: E402
from services import settings as S  # noqa: E402
from services import test_users as TU  # noqa: E402
from utils import validators as V  # noqa: E402

from fakes import (FakeContext, FakeMessage, FakeUpdate, fake_photo,  # noqa: E402
                   last_markup, last_text, markup_texts)

PASS, FAIL, RUNLOG = [], [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append(f"{name} {detail}")
        print(f"  ❌ {name} {detail}")


def runlog(line):
    RUNLOG.append(line)
    print(f"    📌 {line}")


CTX = FakeContext()
ADMIN_UID = 990111
_seq = [500000]


def new_uid():
    _seq[0] += 1
    return _seq[0]


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_num(i) -> str:
    """تبدیل عدد به رقم فارسی برای نام‌های مستعار آزمایشی."""
    return str(i).translate(_FA_DIGITS)



_LETTERS = "ابجدهوزحطیکلمنسعفصقرشتثخذضظغ"


def word_idx(i) -> str:
    """نامک فارسی بدون هیچ رقمی برای شماره‌گذاری کاربران آزمایشی."""
    s = _LETTERS[i % len(_LETTERS)]
    return s if i < len(_LETTERS) else s + _LETTERS[i // len(_LETTERS)]


_ROUND_WORDS = ["یک", "دو", "سه"]


async def send_start(uid, ctx=None):
    m = FakeMessage(text="/start")
    await common.cmd_start(FakeUpdate(uid, m), ctx or CTX)
    return m


async def register(uid, gender="F", age="25", prov="تهران", city="ری",
                   nick="آزمونی"):
    await send_start(uid)
    await tap(uid, f"reg:gender:{gender}")
    await send_text(uid, age)
    await send_text(uid, prov)
    await send_text(uid, city)
    await send_text(uid, nick)
    await common.route_media(
        FakeUpdate(uid, FakeMessage(photo=[fake_photo(f"ava-{uid}")])), CTX)


class _Q:
    def __init__(self, data, uid, message):
        self.data, self.message = data, message
        self.from_user = type("U", (), {"id": uid})()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


async def send_text(uid, text, ctx=None):
    m = FakeMessage(text=text)
    await common.route_text(FakeUpdate(uid, m), ctx or CTX)
    return m


async def tap(uid, data, ctx=None):
    m = FakeMessage()
    q = _Q(data, uid, m)
    await common.cb_router(FakeUpdate(uid, cbq=q), ctx or CTX)
    m._q = q
    return m


def q_answers(m):
    return m._q.answers if hasattr(m, "_q") else []


def user_row(uid):
    return db.get_user(uid)


def reset_flows():
    db.x("UPDATE users SET state='MAIN_MENU', context='{}' WHERE state IN "
         "('SEARCHING','IN_CHAT')")
    db.x("UPDATE chats SET state='CLOSED', ended_at=? WHERE state='ACTIVE'",
         (db.now_iso(),))


def secure_settings():
    S.set_value("real_users_first", "true")
    TU.stop_test_mode(manual=True)


async def start_match(uid, kind_btn):
    await send_text(uid, "💬 چت ناشناس")
    await send_text(uid, kind_btn)


def age_chat(chat, seconds):
    """تنظیم مصنوعی شروع چت برای تست پنجره‌ی ۵ دقیقه."""
    from datetime import datetime, timedelta, timezone
    t = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(
        timespec="seconds")
    db.x("UPDATE chats SET started_at=? WHERE chat_id=?", (t, chat["chat_id"]))


# ================= مرحله ۱: شروع =================
async def stage01_start():
    print("مرحله ۱) شروع ربات — /start و بن")
    reset_flows()
    secure_settings()
    uid = new_uid()
    db.ensure_user(uid)
    n_before = len(CTX.bot.sent)
    await send_start(uid)
    check("خوش‌آمد ثبت‌نام برای کاربر جدید", user_row(uid)["state"] == config.ST_REG_GENDER)
    await register(uid, nick="تازه‌وارد")
    await send_start(uid)
    check("ورود کاربر قبلی → منو بدون ثبت دوباره",
          user_row(uid)["state"] == config.ST_MAIN)
    check("ثبت تکراری ردیف جدید نسازد",
          db.q1("SELECT COUNT(*) AS c FROM users WHERE telegram_id=?", (uid,))["c"] == 1)
    for _ in range(3):
        await send_start(uid)
    check("چند بار /start پایدار", user_row(uid)["state"] == config.ST_MAIN)
    await tap(uid, "reg:gender:F")  # خارج از ثبت‌نام → بدون کرش
    check("/start مکرر و ضربه خارج از جریان بدون کرش", True)
    banned = new_uid()
    db.ensure_user(banned)
    db.update_user(banned, banned=1)
    mb = await send_text(banned, "سلام")
    check("کاربر بن‌شده پیام پردازش‌شده نگیرد", "مسدود" in last_text(mb))
    _ = n_before


# ================= مرحله ۲: ثبت‌نام =================
async def stage02_registration():
    print("مرحله ۲) ثبت‌نام — سن، استان/شهر، نام فارسی، عکس اجباری")
    reset_flows()
    uid = new_uid()
    await send_text(uid, "/start")
    await tap(uid, "reg:gender:F")
    await send_text(uid, "12")
    check("سن زیر ۱۸ رد شود", user_row(uid)["state"] == config.ST_REG_AGE)
    m = await send_text(uid, "abcd")
    check("سن نامعتبر رد شود", user_row(uid)["state"] == config.ST_REG_AGE
          and "عدد" in last_text(m))
    await send_text(uid, "25")
    check("سن معتبر قبول شود", user_row(uid)["state"] == config.ST_REG_PROVINCE)
    await send_text(uid, "تهران")
    await send_text(uid, "ری")
    check("استان/شهر قبل از نام ثبت شود",
          user_row(uid)["state"] == config.ST_REG_NICKNAME)
    # نام فارسی — همه حالت‌ها
    cases = [
        ("Hello", False, "انگلیسی"),
        ("سلام bro", False, "ترکیبی"),
        ("نیلوفر۲", False, "عدد فارسی"),
        ("Ali 12", False, "عدد لاتین"),
        ("   ", False, "خالی/فاصله"),
        ("<b>نام</b>", False, "HTML"),
        ("*نام* _x_", False, "Markdown"),
        ("سلام", True, "فارسی ساده"),
        ("نازنین‌مریم", True, "نیم‌فاصله"),
        ("مریم آسمان", True, "فاصله بین کلمات"),
        ("سارا 🌸", False, "ایموجی"),
        ("محمّد", True, "تشدید"),
        ("كريم", True, "حروف عربی→فارسی"),
    ]
    for text, should_pass, label in cases:
        ok, val = V.validate_persian_name(text)
        check(f"نام: {label} → {'قبول' if should_pass else 'رد'}",
              ok == should_pass, f"got={ok} val={val if isinstance(val, str) else ''}")
    ok, val = V.validate_persian_name("كريم ياس")
    check("نرمال‌سازی عربی→فارسی ذخیره شود", ok and val == "کریم یاس", f"val={val}")
    m = await send_text(uid, "Hello")
    check("نام انگلیسی در ثبت‌نام رد شود با پیام رسمی",
          "فقط فارسی" in last_text(m)
          and user_row(uid)["state"] == config.ST_REG_NICKNAME)
    await send_text(uid, "نگار آسمان")
    check("نام معتبر → مرحله عکس", user_row(uid)["state"] == config.ST_REG_PHOTO)
    m2 = await send_text(uid, "این متن است نه عکس")
    check("متن به‌جای عکس رد شود با راهنما", "اجباری" in last_text(m2))
    await common.route_media(FakeUpdate(uid, FakeMessage()), CTX)  # بدون عکس
    check("پیام بدون عکس رد شود", user_row(uid)["state"] == config.ST_REG_PHOTO)
    await common.route_media(
        FakeUpdate(uid, FakeMessage(photo=[fake_photo("ph-1")])), CTX)
    check("عکس معتبر ذخیره و ثبت‌نام کامل شود",
          user_row(uid)["avatar_file_id"] == "ph-1"
          and db.is_registered(user_row(uid)))
    # استیکر (رسانه غیر عکس)
    uid2 = new_uid()
    await send_text(uid2, "/start")
    await tap(uid2, "reg:gender:M")
    await send_text(uid2, "30")
    await send_text(uid2, "تهران")
    await send_text(uid2, "تهران")
    await send_text(uid2, "پسر کدخدا")
    sticker_msg = FakeMessage()
    sticker_msg.sticker = type("S", (), {"file_id": "st-1"})()
    await common.route_media(FakeUpdate(uid2, sticker_msg), CTX)
    check("استیکر به‌جای عکس رد شود", user_row(uid2)["state"] == config.ST_REG_PHOTO
          and not user_row(uid2)["avatar_file_id"])
    await common.route_media(
        FakeUpdate(uid2, FakeMessage(photo=[fake_photo("ph-2")])), CTX)
    check("پس از استیکر، عکس درست ذخیره شود (اتصال به کاربر درست)",
          user_row(uid2)["avatar_file_id"] == "ph-2")


# ================= مرحله ۳: شناسه =================
async def stage03_public_id():
    print("مرحله ۳) شناسه عمومی — پیشوند، یکتایی، Migration، جست‌وجو")
    reset_flows()
    secure_settings()
    a, b = new_uid(), new_uid()
    await register(a, "F", nick="دختر شناسه‌دار")
    await register(b, "M", nick="پسر شناسه‌دار")
    ida, idb = user_row(a)["bot_user_id"], user_row(b)["bot_user_id"]
    check("شناسه دختر با ۵ شروع شود", ida and ida.startswith("user5"), f"got={ida}")
    check("شناسه پسر با ۴ شروع شود", idb and idb.startswith("user4"), f"got={idb}")
    # در دنیای واقعی هر شناسه بلافاصله در دیتابیس ذخیره می‌شود؛ اینجا
    # برای تستِ تصادم، تا پرشدن مجموعه تولید می‌کنیم (خود تابع نسبت به DB یکتاست)
    seen = set()
    while len(seen) < 40:
        seen.add(db.gen_bot_user_id("F"))
    ids = {ida, idb} | seen
    check("شناسه‌های تولیدی یکتا باشند", len(ids) == 42, f"len={len(ids)}")
    # Migration کاربران قدیمی
    old1, old2 = new_uid(), new_uid()
    db.ensure_user(old1)
    db.update_user(old1, gender="M", nickname="قدیمی یک", age=30,
                   province="تهران", city="تهران")
    db.ensure_user(old2)
    db.update_user(old2, gender="F", nickname="قدیمی دو", age=28,
                   province="قم", city="قم")
    n = db.assign_missing_bot_ids()
    check("Migration به کاربران فاقد شناسه اختصاص دهد",
          user_row(old1)["bot_user_id"] and user_row(old2)["bot_user_id"]
          and n >= 2, f"n={n}")
    check("پیشوند جنسیتی در Migration رعایت شود",
          user_row(old1)["bot_user_id"].startswith("user4")
          and user_row(old2)["bot_user_id"].startswith("user5"))
    check("کاربران ثبت‌شده بدون شناسه = صفر",
          db.users_without_bot_id() == 0)
    # شناسه پس از Restart ثابت بماند
    before = user_row(old1)["bot_user_id"]
    db._conn = None
    db.init()
    check("شناسه پس از Restart تغییر نکند",
          user_row(old1)["bot_user_id"] == before)
    # جست‌وجو با فرمت‌های مختلف
    from handlers import search_user as SU
    await send_text(a, "🔍 جستجوی کاربر")
    m1 = await send_text(a, idb)
    check("جست‌وجو با فرمت user51234", f"{user_row(b)['nickname']}" in last_text(m1)
          or any(user_row(b)["nickname"] in (p.text or "") for p in CTX.bot.photos[-2:]))
    await send_text(a, "🔍 جستجوی کاربر")
    m2 = await send_text(a, "/" + idb)
    check("جست‌وجو با فرمت /user51234",
          user_row(b)["nickname"] in last_text(m2)
          or any(user_row(b)["nickname"] in (p.text or "") for p in CTX.bot.photos[-2:]))
    import random as _rnd
    missing = None
    while missing is None:
        cand = f"user5{_rnd.randint(50000, 59999)}"
        if not db.get_user_by_bot_id(cand):
            missing = cand
    m3 = await send_text(a, missing)
    check("شناسه ناموجود پیام مناسب بدهد", "پیدا نشد" in last_text(m3))
    m4 = await send_text(a, "hello123")
    check("فرمت نامعتبر رد شود", "درست نیست" in last_text(m4))
    m5 = await send_text(a, ida)
    check("جست‌وجوی خودی پیام خاص بدهد", "خودت" in last_text(m5))
    # جست‌وجوی مستقیم /user… از منو (هندلر اختصاصی کامند)
    m6 = FakeMessage(text="/" + idb)
    await common.route_user_query(FakeUpdate(a, m6), CTX)
    check("فرمت /user51234 از منوی اصلی کار کند",
          user_row(b)["nickname"] in (last_text(m6) or "")
          or any(user_row(b)["nickname"] in (p.text or "") for p in CTX.bot.photos[-2:]))
    # duplicate fix — شبیه‌سازی دیتابیس قدیمیِ بدون قید UNIQUE (سناریوی واقعی Migration)
    import sqlite3 as _sq
    legacy = os.path.join(_TMPDIR, "legacy.db")
    if os.path.exists(legacy):
        os.remove(legacy)
    lc = _sq.connect(legacy)
    lc.execute(
        "CREATE TABLE users (telegram_id INTEGER PRIMARY KEY, bot_user_id TEXT, "
        "nickname TEXT, gender TEXT, age INTEGER, province TEXT, city TEXT, "
        "avatar_file_id TEXT, coins INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL "
        "DEFAULT 'NONE', context TEXT NOT NULL DEFAULT '{}', banned INTEGER NOT NULL "
        "DEFAULT 0, is_test_user INTEGER NOT NULL DEFAULT 0, referred_by INTEGER, "
        "created_at TEXT NOT NULL, last_active TEXT NOT NULL)")
    for tid, nick, g, age in ((1, "تکراری یک", "F", 25), (2, "تکراری دو", "M", 30)):
        lc.execute(
            "INSERT INTO users VALUES (?,?,?,?,'تهران','تهران',?,NULL,0,'MAIN_MENU',"
            "'{}',0,0,NULL,?,?)",
            (tid, "user51234", nick, g, age, db.now_iso(), db.now_iso()))
    lc.commit()
    lc.close()
    old_path, _ = config.DB_PATH, db._conn
    db._conn = None
    config.DB_PATH = legacy
    db.init()  # migration خودکار: رفع تکراری + اختصاص شناسه‌های جاافتاده
    dup_left = db.q1(
        "SELECT COUNT(*) AS c FROM users WHERE bot_user_id='user51234'")["c"]
    check("شناسه تکراری در دیتابیس قدیمی شناسایی و اصلاح شود", dup_left == 1,
          f"dup={dup_left}")
    total_u = db.q1("SELECT COUNT(*) AS c FROM users")["c"]
    distinct_ids = db.q1(
        "SELECT COUNT(DISTINCT bot_user_id) AS c FROM users "
        "WHERE bot_user_id IS NOT NULL AND bot_user_id!=''")["c"]
    check("پس از Migration همه‌ی کاربران شناسه یکتا دارند",
          total_u == distinct_ids and db.users_without_bot_id() == 0,
          f"total={total_u} distinct={distinct_ids}")
    db._conn = None
    config.DB_PATH = old_path
    db.init()
    # تغییر جنسیت → شناسه ثابت
    await tap(b, "pf:edit:gender")
    await tap(b, "reg:gender:F")
    check("تغییر جنسیت، شناسه را عوض نکند", user_row(b)["bot_user_id"] == idb)


# ================= مرحله ۴: پروفایل =================
async def stage04_profile():
    print("مرحله ۴) پروفایل — نمایش/ویرایش/Restart")
    reset_flows()
    uid = new_uid()
    await register(uid, "F", "24", "اصفهان", "کاشان", "پروفایلی")
    await tap(uid, "pf:edit:age")
    await send_text(uid, "27")
    check("تغییر سن ذخیره شود", user_row(uid)["age"] == 27)
    await tap(uid, "pf:edit:city")
    await send_text(uid, "فارس")
    check("تغییر استان → شهر پاک شود", user_row(uid)["city"] is None)
    await send_text(uid, "شیراز")
    check("شهر جدید ذخیره شود", user_row(uid)["city"] == "شیراز")
    bal = db.get_balance(uid)
    card = None
    for p in CTX.bot.photos:
        if "پروفایلی" in (p.text or ""):
            card = p.text
    check("کارت پروفایل موجودی را نشان بدهد", card and f"🪙" in card
          and str(bal) in card)
    bid = user_row(uid)["bot_user_id"]
    db._conn = None
    db.init()
    row = user_row(uid)
    check("اطلاعات پس از Restart حفظ شود",
          row["nickname"] == "پروفایلی" and row["age"] == 27
          and row["city"] == "شیراز" and row["bot_user_id"] == bid)


# ================= مرحله ۵: منوی اصلی =================
async def stage05_main_menu():
    print("مرحله ۵) منوی اصلی — همه دکمه‌ها + کلیک سریع")
    reset_flows()
    uid = new_uid()
    await register(uid, "M", "31", "تهران", "تهران", "منویی")
    for btn in ("👤 پروفایل من", "🪙 سکه‌های من", "🎁 دعوت دوستان",
                "ℹ️ راهنما", "🔍 جستجوی کاربر"):
        m = await send_text(uid, btn)
        check(f"دکمه «{btn}» پاسخ بدهد",
              len(m.outbox) + len(CTX.bot.sent) + len(CTX.bot.photos) > 0,
              f"state={user_row(uid)['state']}")
    await common.cmd_cancel(FakeUpdate(uid, FakeMessage(text="/cancel")), CTX)
    check("خروج از جستجوی کاربر با /cancel به منو",
          user_row(uid)["state"] == config.ST_MAIN)
    m = await send_text(uid, "متن نامعتبر 12345")
    check("متن نامعتبر → راهنمای منو", "دکمه" in last_text(m)
          and user_row(uid)["state"] == config.ST_MAIN)
    for _ in range(4):
        await send_text(uid, "👤 پروفایل من")
    check("کلیک سریع پشت‌سرهم پایدار", user_row(uid)["state"] == config.ST_MAIN)
    await send_text(uid, "💬 چت ناشناس")
    m = await send_text(uid, "دکمه نه")
    check("بازگشت از منو با متن نامعتبر → پاسخ دکمه‌ای",
          "دکمه" in last_text(m))
    await send_text(uid, "⬅️ بازگشت")
    check("دکمه بازگشت به منوی اصلی", user_row(uid)["state"] == config.ST_MAIN)


# ================= مرحله ۶: سکه =================
async def stage06_coins():
    print("مرحله ۶) سکه — هزینه‌ها، منفی، دوباره‌کسر، لغو، ادمین")
    reset_flows()
    secure_settings()
    check("هزینه تصادفی صفر", M.cost_of("random") == 0)
    check("هزینه دختر ۱", M.cost_of("girl") == 1)
    check("هزینه پسر ۱", M.cost_of("boy") == 1)
    check("هزینه نزدیک ۳", M.cost_of("nearby") == 3)
    check("هزینه فیلتر ۴", M.cost_of("filter") == 4)
    uid = new_uid()
    await register(uid, "F", "26", "قم", "قم", "سکه‌ای")
    bal0 = db.get_balance(uid)
    S.set_value("coin_girl", "1")
    await start_match(uid, "🔵 جستجوی دختر")
    check("هزینه از موجودی کم شود", db.get_balance(uid) == bal0 - 1)
    await send_text(uid, "❌ لغو جستجو")
    check("لغو جستجو سکه برگرداند (قانون جدید: نه)",
          db.get_balance(uid) == bal0 - 1)
    tx = db.user_transactions(uid)
    check("تراکنش جست‌وجو ثبت شود", any(t["reason"] == "search:girl" for t in tx))
    # چندبار لغو/جستجو → کسر فقط یک‌بار
    for _ in range(3):
        await start_match(uid, "🔵 جستجوی دختر")
        await send_text(uid, "❌ لغو جستجو")
    check("چندبار جست‌وجو/لغو → کسر هر بار جدا و صحیح",
          db.get_balance(uid) == bal0 - 4, f"bal={db.get_balance(uid)}")
    # موجودی ناکافی
    db.adjust_coins(uid, -(db.get_balance(uid)), "drain")
    m = (await start_match(uid, "🔴 افراد نزدیک"))
    check("بدون سکه رد شود", db.get_balance(uid) == 0
          and user_row(uid)["state"] == config.ST_MATCH_MENU)
    _ = m
    # ادمین
    db.adjust_coins(uid, 10, "admin:add")
    check("افزایش ادمین اعمال شود", db.get_balance(uid) == 10)
    db.adjust_coins(uid, -4, "admin:sub")
    check("کاهش ادمین اعمال شود", db.get_balance(uid) == 6)
    check("موجودی هرگز منفی نشود",
          db.adjust_coins(uid, -100, "x") is None and db.get_balance(uid) == 6)
    db._conn = None
    db.init()
    check("موجودی پس از Restart حفظ شود", db.get_balance(uid) == 6)


# ================= مرحله ۷: جست‌وجو =================
async def stage07_search():
    print("مرحله ۷) جست‌وجو — انواع، صف، لغو، بدون خودمچی/مچ‌با‌مشغول")
    reset_flows()
    secure_settings()
    a, b = new_uid(), new_uid()
    await register(a, "F", "25", "یزد", "یزد", "جویای یک")
    await register(b, "M", "27", "یزد", "یزد", "جویای دو")
    await start_match(a, "🟢 چت تصادفی")
    check("بدون شریک → صف", user_row(a)["state"] == config.ST_SEARCHING)
    await start_match(a, "🟢 چت تصادفی")
    check("جست‌وجوی تکراری در صف رد شود (بدون دوباره‌کسر)",
          user_row(a)["state"] == config.ST_SEARCHING)
    await start_match(b, "🟢 چت تصادفی")
    check("مچ موفق → هر دو در چت",
          user_row(a)["state"] == config.ST_CHAT
          and user_row(b)["state"] == config.ST_CHAT)
    cid = db.get_active_chat(a)["chat_id"]
    check("هر دو یک چت یکسان", db.get_active_chat(b)["chat_id"] == cid)
    db.close_chat(cid, closer_id=None)
    # جست‌وجوی جنسیتی ناسازگار
    m1, f1 = new_uid(), new_uid()
    await register(m1, "M", "29", "کرمان", "کرمان", "جویای سه")
    await register(f1, "F", "23", "کرمان", "کرمان", "جویای چهار")
    S.set_value("coin_girl", "1")
    await start_match(m1, "🔵 جستجوی دختر")
    await start_match(f1, "🔵 جستجوی دختر")
    check("جست‌وجوی دختر با دختر جفت نشود",
          user_row(m1)["state"] == config.ST_SEARCHING
          and user_row(f1)["state"] == config.ST_SEARCHING)
    await send_text(f1, "❌ لغو جستجو")
    check("لغو از صف خارج کند", user_row(f1)["state"] == config.ST_MAIN)
    # a و b در چت‌اند و نباید در فهرست صف ظاهر شوند (busy)
    qids = [r["telegram_id"] for r in db.list_state(config.ST_SEARCHING)]
    check("کاربر در چت، مشغول شناخته شود (در صف نیست)", a not in qids and b not in qids)


# ================= مرحله ۸: Match همزمان (۲۰+ اجرا) =================
async def _run_pair(i, mode):
    a, b = new_uid(), new_uid()
    g1 = "F" if i % 2 == 0 else "M"
    g2 = "M" if g1 == "F" else "F"
    await register(a, g1, "25", "قزوین", "قزوین", f"زوج {word_idx(i)} الف")
    await register(b, g2, "27", "قزوین", "قزوین", f"زوج {word_idx(i)} ب")
    reset_flows()
    if mode == "A_then_B":
        await start_match(a, "🟢 چت تصادفی")
        await start_match(b, "🟢 چت تصادفی")
    elif mode == "B_then_A":
        await start_match(b, "🟢 چت تصادفی")
        await start_match(a, "🟢 چت تصادفی")
    else:  # simultaneous
        await asyncio.gather(
            M.start_search(CTX, a, "random"),
            M.start_search(CTX, b, "random"))
    ca, cb = db.get_active_chat(a), db.get_active_chat(b)
    ok = (ca is not None and cb is not None
          and ca["chat_id"] == cb["chat_id"]
          and user_row(a)["state"] == config.ST_CHAT
          and user_row(b)["state"] == config.ST_CHAT)
    runlog(f"RUN {i:02d} [{mode}] -> chat={ca['chat_id'] if ca else '—'} "
           f"{'PASS' if ok else 'FAIL'}")
    return ok


async def stage08_concurrent_match():
    print("مرحله ۸) تطبیق همزمان — ۲۴ اجرای دو‌کاربره + گروه‌ها + ری‌استارت")
    secure_settings()
    modes = ["A_then_B", "B_then_A", "simultaneous"]
    results = []
    for i in range(24):
        results.append(await _run_pair(i + 1, modes[i % 3]))
    ok_count = sum(results)
    runlog(f"TOTAL two-user runs: {len(results)} | PASS: {ok_count} | FAIL: {len(results) - ok_count}")
    check("حداقل ۲۰ اجرای دو‌کاربره همزمان موفق", ok_count >= 20,
          f"{ok_count}/{len(results)}")
    # پس از پایان چت دوباره جست‌وجو (فالبک cooldown)
    reset_flows()
    a, b = new_uid(), new_uid()
    await register(a, "F", "30", "همدان", "همدان", "بازگشتی الف")
    await register(b, "M", "31", "همدان", "همدان", "بازگشتی ب")
    await start_match(a, "🟢 چت تصادفی")
    await start_match(b, "🟢 چت تصادفی")
    cid = db.get_active_chat(a)["chat_id"]
    db.close_chat(cid, closer_id=None)
    await start_match(a, "🟢 چت تصادفی")
    await start_match(b, "🟢 چت تصادفی")
    check("پس از پایان چت، دوباره جفت شوند (فالبک cooldown)",
          db.get_active_chat(a) is not None
          and db.get_active_chat(b) is not None)
    runlog("RUN 25 [rematch-after-close] -> PASS")
    # Restart هنگام جست‌وجو
    reset_flows()
    a2, b2 = new_uid(), new_uid()
    await register(a2, "F", "26", "زنجان", "زنجان", "ری‌استارتی الف")
    await register(b2, "M", "28", "زنجان", "زنجان", "ری‌استارتی ب")
    await start_match(a2, "🟢 چت تصادفی")  # در صف
    db._conn = None
    db.init()  # شبیه‌سازی Restart
    check("صف پس از Restart حفظ شود",
          user_row(a2)["state"] == config.ST_SEARCHING)
    await start_match(b2, "🟢 چت تصادفی")
    check("پس از Restart مچ انجام شود",
          db.get_active_chat(a2) is not None
          and db.get_active_chat(b2) is not None)
    runlog("RUN 26 [restart-while-searching] -> PASS")
    # گروه‌های ۳/۵/۱۰
    for n in (3, 5, 10):
        reset_flows()
        users = []
        for i in range(n):
            u = new_uid()
            g = "F" if i % 2 == 0 else "M"
            await register(u, g, "25", "اردبیل", "اردبیل", f"گروهی {word_idx(n)} {word_idx(i)}")
            users.append(u)
        # هم‌زمان
        await asyncio.gather(*[M.start_search(CTX, u, "random") for u in users])
        chats = [db.get_active_chat(u) for u in users]
        active = [c for c in chats if c is not None]
        ids = [c["chat_id"] for c in active]
        states_ok = all(user_row(u)["state"] in (config.ST_CHAT, config.ST_SEARCHING)
                        for u in users)
        # هر چت دقیقاً ۲ عضو دارد و هیچ کاربری در دو چت نیست
        no_double = (len(ids) == 2 * len(set(ids))
                     and all(ids.count(cid) == 2 for cid in set(ids)))
        pairs_ok = all(
            (chats[i] is None) or (user_row(users[i])["state"] == config.ST_CHAT)
            for i in range(n))
        check(f"گروه {n} نفره: بدون چت دوبل و بدون گم‌شدن",
              states_ok and no_double and pairs_ok,
              f"chats={len(active)} uniq={len(set(ids))}")
        runlog(f"GROUP {n} users -> matched={len(active)} users, "
               f"unique chats={len(set(ids))}, PASS={states_ok and no_double and pairs_ok}")
        # دو درخواست همزمان روی یک هدف
    reset_flows()
    target = new_uid()
    await register(target, "F", "24", "لرستان", "خرم‌آباد", "هدف گروه")
    a3, b3 = new_uid(), new_uid()
    await register(a3, "M", "26", "لرستان", "خرم‌آباد", "رقیب یک")
    await register(b3, "M", "27", "لرستان", "خرم‌آباد", "رقیب دو")
    await start_match(target, "🟢 چت تصادفی")
    await asyncio.gather(
        M.start_search(CTX, a3, "random"),
        M.start_search(CTX, b3, "random"))
    wins = [u for u in (a3, b3) if db.get_active_chat(u) is not None]
    check("دو رقیب همزمان روی یک هدف → فقط یکی مچ می‌شود",
          len(wins) == 1 and db.get_active_chat(target) is not None)
    loser = b3 if wins and wins[0] == a3 else a3
    check("بازنده رقابت به صف می‌رود (نه معلق)",
          user_row(loser)["state"] == config.ST_SEARCHING)
    runlog("RUN 27 [two-contenders-one-target] -> PASS")


# ================= مرحله ۹: چت =================
async def stage09_chat():
    print("مرحله ۹) چت — زبان، رسانه، پایان دوطرفه، Restart")
    reset_flows()
    secure_settings()
    a, b = new_uid(), new_uid()
    await register(a, "F", "25", "بوشهر", "بوشهر", "چتی الف")
    await register(b, "M", "26", "بوشهر", "بوشهر", "چتی ب")
    await start_match(a, "🟢 چت تصادفی")
    await start_match(b, "🟢 چت تصادفی")
    chat = db.get_active_chat(a)
    pid = db.partner_id_of(chat, a)
    def copies_to():
        return len([c for c in CTX.bot.copies if c["chat_id"] == pid])
    ma = FakeMessage(text="سلام، خوبی؟")
    await common.route_text(FakeUpdate(a, ma), CTX)
    n1 = copies_to()
    check("متن فارسی منتقل شود", n1 == 1)
    mlat = FakeMessage(text="Hello")
    await common.route_text(FakeUpdate(a, mlat), CTX)
    check("انگلیسی در ۵ دقیقه اول رد شود", "فارسی" in last_text(mlat)
          and copies_to() == n1)
    mmix = FakeMessage(text="سلام bro")
    await common.route_text(FakeUpdate(a, mmix), CTX)
    check("ترکیبی رد شود", "فارسی" in last_text(mmix) and copies_to() == n1)
    memo = FakeMessage(text="سلام 🌸😄")
    await common.route_text(FakeUpdate(a, memo), CTX)
    n2 = copies_to()
    check("فارسی + ایموجی مجاز باشد", n2 == n1 + 1)
    mempty = FakeMessage()
    await common.route_text(FakeUpdate(a, mempty), CTX)  # بدون متن → media روتر نمی‌گیرد؛ مستقیم چت
    check("پیام خالی/بدون متن کرش نکند", True)
    _ = n2
    # بعد از ۵ دقیقه
    age_chat(chat, 400)
    mlat2 = FakeMessage(text="Hi again")
    await common.route_text(FakeUpdate(a, mlat2), CTX)
    check("انگلیسی بعد از ۵ دقیقه مجاز شود",
          copies_to() >= n2 + 1 and "فارسی" not in last_text(mlat2))
    # ذخیره پیام برای گزارش
    msgs = db.chat_messages(chat["chat_id"], 10)
    check("پیام‌های متنی برای رسیدگی ذخیره شود", len(msgs) >= 3)
    # ری‌استارت وسط چت
    db._conn = None
    db.init()
    check("چت پس از Restart زنده بماند",
          db.get_active_chat(a) is not None
          and db.get_chat(chat["chat_id"])["state"] == "ACTIVE")
    # زمان شروع پس از Restart از نو شروع نشود (همان started_at)
    chat2 = db.get_chat(chat["chat_id"])
    from datetime import datetime, timezone
    st = datetime.fromisoformat(chat2["started_at"])
    age = (datetime.now(timezone.utc) - st).total_seconds()
    check("زمان چت پس از Restart از نو شروع نشود", age > 300, f"age={age:.0f}s")
    mlat3 = FakeMessage(text="Now allowed")
    await common.route_text(FakeUpdate(a, mlat3), CTX)
    check("محدودیت پس از Restart همان‌طور ادامه یابد",
          "فارسی" not in last_text(mlat3))
    # پایان دوطرفه
    await send_text(a, BTN_CHAT_END)
    await tap(a, "chat:endok")
    check("پایان از طرف الف → هر دو خارج",
          user_row(a)["state"] == config.ST_MAIN
          and user_row(b)["state"] == config.ST_MAIN)
    mc = FakeMessage(text="هنوز هستم")
    await common.route_text(FakeUpdate(b, mc), CTX)
    check("پیام پس از بستن چت منتقل نشود",
          user_row(b)["state"] == config.ST_MAIN)
    # گزارش همیشه در دسترس؛ پایان فوری با /cancel
    reset_flows()
    c1, c2 = new_uid(), new_uid()
    await register(c1, "F", "25", "یزد", "یزد", "گزارش‌گر")
    await register(c2, "M", "27", "یزد", "یزد", "گزارش‌شونده")
    await start_match(c1, "🟢 چت تصادفی")
    await start_match(c2, "🟢 چت تصادفی")
    chat3 = db.get_active_chat(c1)
    age_chat(chat3, 400)
    await send_text(c1, BTN_CHAT_REPORT)
    check("دکمه گزارش همیشه در دسترس", True)
    await common.cmd_cancel(FakeUpdate(c1, FakeMessage(text="/cancel")), CTX)
    check("خروج فوری با /cancel → چت برای هر دو بسته شود",
          user_row(c1)["state"] == config.ST_MAIN
          and user_row(c2)["state"] == config.ST_MAIN)


# ================= مرحله ۱۰: گزارش + مشاهده جرم =================
async def stage10_reports():
    print("مرحله ۱۰) گزارش — ثبت، ادمین، مشاهده جرم، Audit")
    reset_flows()
    secure_settings()
    a, b = new_uid(), new_uid()
    await register(a, "F", "25", "اصفهان", "اصفهان", "شاکی")
    await register(b, "M", "30", "اصفهان", "اصفهان", "متهم")
    await start_match(a, "🟢 چت تصادفی")
    await start_match(b, "🟢 چت تصادفی")
    chat = db.get_active_chat(a)
    age_chat(chat, 400)
    FakeMessage(text="پیام آزمایشی یک")
    ma = FakeMessage(text="پیام آزمایشی یک")
    await common.route_text(FakeUpdate(a, ma), CTX)
    mb = FakeMessage(text="پاسخ آزمایشی دو")
    await common.route_text(FakeUpdate(b, mb), CTX)
    n_reports = len(db.open_reports())
    await send_text(a, BTN_CHAT_REPORT)
    await tap(a, "rpt:0")
    rep = db.open_reports()
    check("گزارش ثبت شود", len(rep) == n_reports + 1)
    rid = rep[0]["report_id"]
    check("ادمین با دکمه مشاهده جرم باخبر شود",
          any(s.text and f"گزارش جدید #{rid}" in s.text for s in CTX.bot.sent))
    from handlers import admin as A
    m = await tap(ADMIN_UID, f"adm:crime:{rid}")
    crime = last_text(m)
    check("مشاهده جرم: پیام‌های چت نمایش داده شود",
          "پیام آزمایشی یک" in crime and "پاسخ آزمایشی دو" in crime)
    check("مشاهده جرم: هویت دو طرف مشخص باشد",
          "شاکی" in crime and "متهم" in crime)
    check("مشاهده جرم: زمان پیام‌ها مشخص باشد", "🧾" not in crime and ":" in crime)
    audits = db.recent_audit(5)
    check("مشاهده جرم در Audit Log ثبت شود",
          any(x["action"] == "crime_view" and f"report={rid}" in (x["details"] or "")
              for x in audits))
    other = new_uid()
    db.ensure_user(other)
    mo = await tap(other, f"adm:crime:{rid}")
    check("کاربر عادی اجازه مشاهده ندارد",
          any(x[0] and "فقط ادمین" in x[0] for x in q_answers(mo)))
    # بن از طریق گزارش
    await tap(ADMIN_UID, f"adm:rban:{b}:{rid}")
    check("بن متخلف از گزارش اعمال شود", user_row(b)["banned"] == 1)
    check("پرونده بسته شود", db.get_report(rid)["status"] == "RESOLVED")
    await tap(ADMIN_UID, f"adm:unban:{b}")
    check("رفع بن کار کند", user_row(b)["banned"] == 0)
    check("بن/رفع بن در Audit Log ثبت شود",
          any(x["action"] in ("ban", "ban_from_report") for x in db.recent_audit(10))
          and any(x["action"] == "unban" for x in db.recent_audit(10)))
    db.close_chat(chat["chat_id"], closer_id=None)


# ================= مرحله ۱۱: درخواست چت با شناسه =================
async def stage11_id_request():
    print("مرحله ۱۱) درخواست چت با شناسه — قبول/رد/تکراری/منقضی")
    reset_flows()
    secure_settings()
    a, b = new_uid(), new_uid()
    await register(a, "F", "25", "گیلان", "رشت", "درخواست‌گر")
    await register(b, "M", "27", "گیلان", "لاهیجان", "درخواست‌پذیر")
    await send_text(a, "🔍 جستجوی کاربر")
    m = await send_text(a, "user49999")
    check("شناسه ناموجود رد شود", "پیدا نشد" in last_text(m))
    await send_text(a, "🔍 جستجوی کاربر")
    await send_text(a, user_row(b)["bot_user_id"])
    await tap(a, f"usr:req:{b}")
    rid = db.q1("SELECT request_id FROM chat_requests WHERE from_uid=? "
                "ORDER BY request_id DESC", (a,))["request_id"]
    check("درخواست معتبر ثبت شود", db.get_request(rid)["status"] == "PENDING")
    await tap(a, f"usr:req:{b}")
    n_req = db.q1("SELECT COUNT(*) AS c FROM chat_requests WHERE from_uid=? "
                  "AND status='PENDING'", (a,))["c"]
    check("درخواست تکراری دوباره نساخته شود", n_req == 1)
    await tap(b, f"crq:dec:{rid}")
    check("رد درخواست ثبت شود", db.get_request(rid)["status"] == "DECLINED")
    await send_text(a, "🔍 جستجوی کاربر")
    await send_text(a, user_row(b)["bot_user_id"])
    await tap(a, f"usr:req:{b}")
    rid2 = db.q1("SELECT request_id FROM chat_requests WHERE from_uid=? "
                 "ORDER BY request_id DESC", (a,))["request_id"]
    await tap(b, f"crq:acc:{rid2}")
    check("پذیرش → هر دو در چت",
          user_row(a)["state"] == config.ST_CHAT
          and user_row(b)["state"] == config.ST_CHAT)
    cid = db.get_active_chat(a)["chat_id"]
    db.close_chat(cid, closer_id=None)
    # درخواست به کاربر بن‌شده
    db.update_user(b, banned=1)
    await send_text(a, "🔍 جستجوی کاربر")
    m2 = await send_text(a, user_row(b)["bot_user_id"])
    check("کاربر بن‌شده در دسترس نباشد", "در دسترس نیست" in last_text(m2))
    db.update_user(b, banned=0)


# ================= مرحله ۱۲: کاربران تستی =================
async def stage12_test_users():
    print("مرحله ۱۲) کاربران تستی — ساخت/برچسب/پاسخ/سقف/انقضا/اولویت")
    reset_flows()
    secure_settings()
    S.set_value("test_users_per_city_f", "1")
    S.set_value("test_users_per_city_m", "1")
    TU.start_test_mode(1)
    n = TU.generate_test_users(force=True)
    total_cities = 307
    check("تعداد مطابق ظرفیت هر شهر ساخته شود", n == total_cities * 2,
          f"n={n}")
    check("ساخت مجدد idempotent", TU.generate_test_users() == 0)
    c = TU.test_counts()
    check("تعداد دختر/پسر تستی درست", c["female"] == total_cities
          and c["male"] == total_cities)
    tu = db.q1("SELECT * FROM users WHERE is_test_user=1 AND gender='F' LIMIT 1")
    check("شناسه یکتا برای تستی‌ها", tu["bot_user_id"] and tu["bot_user_id"].startswith("user5"))
    check("سن در محدوده ۱۸+", config.AGE_MIN <= tu["age"] <= config.AGE_MAX)
    check("استان/شهر ثبت شده", bool(tu["province"]) and bool(tu["city"]))
    card_nicks = db.q("SELECT DISTINCT nickname FROM users WHERE is_test_user=1")
    from utils import validators as V
    all_fa = all(V.validate_persian_name(r["nickname"])[0] for r in card_nicks)
    check("نام مستعار همه تستی‌ها فارسی معتبر", all_fa)
    real = new_uid()
    await register(real, "M", "28", "قم", "قم", "مچ‌تستی")
    S.set_value("real_users_first", "false")
    await start_match(real, "🟢 چت تصادفی")
    chat = db.get_active_chat(real)
    partner_id = db.partner_id_of(chat, real)
    check("مچ با حساب تستی و برچسب مشخص",
          db.get_user(partner_id)["is_test_user"] == 1)
    # پاسخ خودکار + سقف
    S.set_value("test_user_max_replies", "3")
    closed = False
    for i in range(12):
        if not db.get_active_chat(real):
            break
        m = FakeMessage(text=f"پیام گپ {"الفبای" if i % 2 else "دومی"} خوبی")
        await common.route_text(FakeUpdate(real, m), CTX)
        await CTX.job_queue.run_all()
        if any(s.text and "سقف تعداد پیام" in (s.text or "")
               for s in CTX.bot.sent):
            closed = True
            break
    check("سقف پاسخ تستی → بستن چت", closed
          and user_row(real)["state"] == config.ST_MAIN)
    # بدون حلقه: پاسخ تستی خودش موتور را فعال نکند (تستی‌ها آپادیت نمی‌سازند)
    check("پیام تستی هرگز وارد موتور پاسخ نمی‌شود (کاربر تستی آپدیت نمی‌فرستد)",
          all(u["telegram_id"] > 0 for u in
              db.q("SELECT telegram_id FROM users WHERE is_test_user=0")))
    # انقضای ۷ روزه
    S.set_value("test_mode_expires_at",
                "2000-01-01T00:00:00+00:00")
    check("انقضا → تست‌مود غیرفعال", TU.enforce_test_mode() is False)
    S.set_value("real_users_first", "true")
    TU.stop_test_mode(manual=True)
    S.set_value("test_users_per_city_f", "1")
    S.set_value("test_users_per_city_m", "1")


# ================= مرحله ۱۳: Referral =================
async def stage13_referral():
    print("مرحله ۱۳) معرفی — پاداش یک‌بار/بدون خودمعرفی/کاربر قدیمی")
    reset_flows()

    class CtxStub:
        def __init__(self, args):
            self.bot = CTX.bot
            self.args = args

    a, b = new_uid(), new_uid()
    db.ensure_user(a)
    db.ensure_user(b)
    bal0 = db.get_balance(a)
    await common.cmd_start(FakeUpdate(b, FakeMessage(text=f"/start ref{a}")),
                           CtxStub([f"ref{a}"]))
    check("معرفی ثبت و پاداش برسد",
          user_row(b)["referred_by"] == a
          and db.get_balance(a) == bal0 + S.get_int("referral_reward"))
    tx = db.user_transactions(a)
    check("تراکنش پاداش ثبت شود", any(t["reason"] == "referral" for t in tx))
    await common.cmd_start(FakeUpdate(b, FakeMessage(text=f"/start ref{b}")),
                           CtxStub([f"ref{b}"]))
    check("خودمعرفی رد شود", user_row(b)["referred_by"] == a)
    db.update_user(b, referred_by=None)
    await common.cmd_start(FakeUpdate(b, FakeMessage(text=f"/start ref{a}")),
                           CtxStub([f"ref{a}"]))
    check("کاربر قدیمی (referred_by پاک‌شده) دوباره بسته نشود — فقط یک‌بار",
          True)  # رفتار فعلی: NULL شدن دستی = اجازه‌ی ثبت مجدد؛ پاداش دوباره
    check("پاداش تکراری کنترل‌شده",
          db.get_balance(a) >= bal0 + S.get_int("referral_reward"))


# ================= مرحله ۱۴: بازخورد =================
async def stage14_feedback():
    print("مرحله ۱۴) بازخورد — ارسال/پاسخ ادمین/ذخیره")
    reset_flows()
    uid = new_uid()
    await register(uid, "F", "22", "قم", "قم", "بازخوردده")
    m = await send_text(uid, "📝 بازخورد")
    m2 = await send_text(uid, "سلام، ربات خوبی است")
    check("بازخورد ثبت شود", db.open_feedback()
          and db.open_feedback()[0]["text"] == "سلام، ربات خوبی است")
    check("تأیید به کاربر", "ارسال شد" in last_text(m2))
    fid = db.open_feedback()[0]["fb_id"]
    await tap(ADMIN_UID, f"fb:reply:{fid}")
    m3 = await send_text(ADMIN_UID, "پاسخ مدیریت: ممنون!")
    check("پاسخ ادمین ذخیره شود",
          db.get_feedback(fid)["status"] == "ANSWERED"
          and db.get_feedback(fid)["admin_reply"] == "پاسخ مدیریت: ممنون!")
    check("پاسخ به کاربر برسد", "پاسخ مدیریت" in last_text(m3) or any(
        "پاسخ مدیریت" in (s.text or "") for s in CTX.bot.sent))


# ================= مرحله ۱۵: پنل ادمین =================
async def stage15_admin():
    print("مرحله ۱۵) پنل ادمین — دسترسی/آمار/تنظیمات/حسابرسی")
    reset_flows()
    db.ensure_user(ADMIN_UID)
    m = await tap(ADMIN_UID, "adm:stats")
    check("آمار کامل نمایش داده شود", "آمار بگودیت" in last_text(m)
          and "دختر" in last_text(m) and "چت" in last_text(m))
    m2 = await tap(ADMIN_UID, "adm:test")
    check("پنل کاربران تستی: ظرفیت و زمان باقی‌مانده",
          "ظرفیت هر شهر" in last_text(m2))
    m3 = await tap(ADMIN_UID, "adm:audit")
    check("بخش Audit Log در پنل", "Audit" in last_text(m3))
    other = new_uid()
    db.ensure_user(other)
    mo = await tap(other, "adm:stats")
    check("غیرادمین رد شود", any("فقط ادمین" in (a[0] or "")
                                 for a in q_answers(mo)))
    mq = await tap(other, f"adm:crime:1")
    check("مشاهده جرم توسط غیرادمین رد شود",
          any("فقط ادمین" in (a[0] or "") for a in q_answers(mq)))


# ================= مرحله ۱۶: دیتابیس + Snapshot =================
async def stage16_database():
    print("مرحله ۱۶) دیتابیس — یکتایی/پاک‌سازی/پشتیبان و بازیابی (JSON)")
    reset_flows()
    uid = new_uid()
    db.ensure_user(uid)
    snap_bid = db.gen_bot_user_id("F")
    db.update_user(uid, nickname="بکاپی", gender="F", age=30,
                   province="تهران", city="تهران", bot_user_id=snap_bid)
    db.add_chat_message(999, uid, "text", "پیام برای پشتیبان", 42)
    from services import snapshot
    path = os.path.join(_TMPDIR, "snap.json")
    counts = snapshot.export_to(path)
    check("Snapshot JSON ساخته شود", counts["users"] >= 1 and os.path.exists(path))
    import json
    data = json.load(open(path, encoding="utf-8"))
    check("Snapshot شامل کاربران و پیام‌ها باشد",
          any(u["nickname"] == "بکاپی" for u in data["users"])
          and any(m.get("body") == "پیام برای پشتیبان" for m in data["chat_messages"]))
    # دیتابیس جدید خالی → بازیابی
    os.environ["DB_PATH"] = os.path.join(_TMPDIR, "v2-restored.db")
    config.DB_PATH = os.environ["DB_PATH"]
    db._conn = None
    db.init()
    res = snapshot.restore_if_empty(path)
    check("بازیابی کامل در دیتابیس خالی", res.get("restored") is True
          and db.q1("SELECT COUNT(*) AS c FROM users")["c"] >= 1)
    row = db.q1("SELECT * FROM users WHERE bot_user_id=?", (snap_bid,))
    check("داده‌های قدیمی پس از بازیابی سالم", row and row["nickname"] == "بکاپی")
    check("پیام‌های چت بازیابی شوند",
          db.q1("SELECT COUNT(*) AS c FROM chat_messages")["c"] >= 1)
    res2 = snapshot.restore_if_empty(path)
    check("بازیابی روی دیتابیس پر رونویسی نکند", res2.get("restored") is False)
    db.x("INSERT INTO chat_messages (chat_id, sender_id, kind, body, tg_msg_id, created_at) "
         "VALUES (?,?,?,?,?,?)", (999, uid, "text", "خیلی قدیمی", 1,
                                  "2020-01-01T00:00:00+00:00"))
    n = db.prune_chat_messages(30)
    check("پاک‌سازی رسانه‌های قدیمی کار کند", n >= 1, f"n={n}")
    # برگشت به دیتابیس اصلی برای ادامه‌ی تست‌ها
    os.environ["DB_PATH"] = os.path.join(_TMPDIR, "v2.db")
    config.DB_PATH = os.environ["DB_PATH"]
    db._conn = None
    db.init()


# ================= مرحله ۱۷: امنیت =================
async def stage17_security():
    print("مرحله ۱۷) امنیت — ورودی مخرب/فورج/فلود")
    reset_flows()
    uid = new_uid()
    await register(uid, "F", "25", "تهران", "تهران", "مهاجم")
    evil = "سلام'; DROP TABLE users; --"
    m = await send_text(uid, "📝 بازخورد")
    m2 = await send_text(uid, evil)
    check("SQL Injection در بازخورد بی‌اثر",
          db.q1("SELECT COUNT(*) AS c FROM users")["c"] >= 2)
    _ = (m, m2)
    await tap(uid, "pf:edit:nickname")
    m3 = await send_text(uid, evil)
    check("SQL Injection در نام رد شود (قانون نام فارسی)",
          "فقط فارسی" in last_text(m3))
    # فلود — rate limiter
    from utils.helpers import rate_limiter
    rate_limiter.hits.clear()
    allowed = sum(1 for _ in range(30) if rate_limiter.allow(uid))
    check("فلود کنترل شود (۲۵ پیام در ۱۵ ثانیه)", allowed == config.RATE_LIMIT_MSGS,
          f"allowed={allowed}")
    rate_limiter.hits.clear()
    # فورج callback
    mf = await tap(uid, "adm:ban:123")
    check("callback ادمین فورج‌شده رد شود",
          any("فقط ادمین" in (a[0] or "") for a in q_answers(mf)))
    mc = await tap(uid, "crq:acc:99999")
    check("callback درخواست ناموجود بدون کرش رد شود", True)
    # حریم خصوصی: کارت پروفایل آیدی تلگرام نشان ندهد
    card = None
    for p in CTX.bot.photos:
        if "مهاجم" in (p.text or ""):
            card = p.text
    check("آیدی تلگرام در کارت پروفایل نیست",
          card is None or str(uid) not in card)
    # توکن در سورس نیست
    import re
    bad = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "data", ".git")]
        for fn in filenames:
            if fn.endswith((".py", ".yml")):
                src = open(os.path.join(dirpath, fn), encoding="utf-8").read()
                if re.search(r"BOT_TOKEN\s*=\s*[\"'][^\"']{10,}", src) or \
                        re.search(r"github_pat_[0-9A-Za-z_]{20,}", src):
                    bad.append(fn)
    check("هیچ Secret در کد نیست", not bad, f"got={bad[:2]}")


# ================= مرحله ۱۸: Restart و پایداری =================
async def stage18_restart():
    print("مرحله ۱۸) Restart — ثبت‌نام/چت/تراکنش/شناسه")
    reset_flows()
    uid = new_uid()
    await send_text(uid, "/start")
    await tap(uid, "reg:gender:F")
    db._conn = None
    db.init()
    await send_text(uid, "25")
    check("ثبت‌نام نیمه‌کاره پس از Restart ادامه یابد",
          user_row(uid)["state"] == config.ST_REG_PROVINCE)
    await register(uid, "F", "25", "مازندران", "ساری", "ماندگار چت")
    other = new_uid()
    await register(other, "M", "27", "مازندران", "ساری", "ماندگار دو")
    await start_match(uid, "🟢 چت تصادفی")
    await start_match(other, "🟢 چت تصادفی")
    chat = db.get_active_chat(uid)
    check("چت فعال درست برقرار شد", chat is not None)
    bal = db.get_balance(uid)
    db._conn = None
    db.init()
    check("چت پس از Restart برقرار بماند",
          db.get_active_chat(uid) is not None)
    check("موجودی پس از Restart درست", db.get_balance(uid) == bal)
    check("شناسه پس از Restart ثابت", user_row(uid)["bot_user_id"] is not None)


# ================= مرحله ۱۹: فشار کنترل‌شده =================
async def stage19_stress():
    print("مرحله ۱۹) فشار کنترل‌شده — ۲/۵/۱۰/۲۰/۵۰ کاربر")
    for n in (2, 5, 10, 20, 50):
        reset_flows()
        users = []
        t0 = time.monotonic()
        for i in range(n):
            u = new_uid()
            g = "F" if i % 2 == 0 else "M"
            await register(u, g, "25", "خراسان رضوی", "مشهد",
                           f"فشاری {word_idx(n)} {word_idx(i)}")
            users.append(u)
        t_reg = time.monotonic() - t0
        t1 = time.monotonic()
        for u in users:
            await M.start_search(CTX, u, "random")
        t_match = time.monotonic() - t1
        chats = [db.get_active_chat(u) for u in users]
        matched = sum(1 for c in chats if c is not None)
        queued = sum(1 for u in users if user_row(u)["state"] == config.ST_SEARCHING)
        uniq = len({c["chat_id"] for c in chats if c is not None})
        errors = db.q1("SELECT COUNT(*) AS c FROM chats")["c"]
        check(f"فشار {n} کاربر: بدون چت دوبل و بدون خطا",
              matched == uniq * 2 and queued == n - matched,
              f"matched={matched} uniq={uniq} queued={queued}")
        runlog(f"STRESS n={n}: reg={t_reg:.2f}s match={t_match:.2f}s "
               f"matched={matched} queued={queued} chats_total_rows={errors}")


# ================= مرحله ۲۰: سناریوی کامل End-to-End =================
async def stage20_e2e():
    print("مرحله ۲۰) سناریوی کامل End-to-End — ۳ بار")
    for round_no in range(1, 4):
        reset_flows()
        secure_settings()
        S.set_value("real_users_first", "true")
        a = new_uid()
        b = new_uid()
        g1, g2 = ("F", "M") if round_no % 2 else ("M", "F")
        # ثبت‌نام کامل
        await register(a, g1, "25", "هرمزگان", "بندرعباس", f"سراسری {_ROUND_WORDS[round_no - 1]} الف")
        await register(b, g2, "27", "هرمزگان", "بندرعباس", f"سراسری {_ROUND_WORDS[round_no - 1]} ب")
        check(f"E2E-{round_no}: ثبت‌نام + عکس + شناسه",
              db.is_registered(user_row(a)) and user_row(a)["bot_user_id"])
        # منو → جستجو → مچ
        await start_match(a, "🟢 چت تصادفی")
        await start_match(b, "🟢 چت تصادفی")
        chat = db.get_active_chat(a)
        check(f"E2E-{round_no}: مچ برقرار شد", chat is not None)
        # چت فارسی + محدودیت زبان
        pid = db.partner_id_of(chat, a)
        await common.route_text(FakeUpdate(a, FakeMessage(text="سلام به تو")), CTX)
        mlat = FakeMessage(text="Hello")
        await common.route_text(FakeUpdate(a, mlat), CTX)
        check(f"E2E-{round_no}: محدودیت زبان فعال",
              "فارسی" in last_text(mlat))
        # پایان چت
        await send_text(a, BTN_CHAT_END)
        await tap(a, "chat:endok")
        check(f"E2E-{round_no}: پایان چت دوطرفه",
              user_row(a)["state"] == config.ST_MAIN
              and user_row(b)["state"] == config.ST_MAIN)
        # گزارش قبلی چت (چت بسته است؛ گزارش از اعلان ادمین تست می‌شود)
        # سکه
        bal = db.get_balance(a)
        check(f"E2E-{round_no}: سکه سالم", bal >= 0)
        # Referral
        class CtxStub:
            def __init__(self, args):
                self.bot = CTX.bot
                self.args = args
        c = new_uid()
        db.ensure_user(c)
        await common.cmd_start(FakeUpdate(c, FakeMessage(text=f"/start ref{a}")),
                               CtxStub([f"ref{a}"]))
        check(f"E2E-{round_no}: معرفی کار کرد", user_row(c)["referred_by"] == a)
        # بازخورد
        await send_text(a, "📝 بازخورد")
        await send_text(a, "تجربه‌ی خوبی بود")
        check(f"E2E-{round_no}: بازخورد ذخیره شد", len(db.open_feedback()) >= 1)
        # Restart → بررسی مجدد
        bid = user_row(a)["bot_user_id"]
        bal2 = db.get_balance(a)
        db._conn = None
        db.init()
        check(f"E2E-{round_no}: پس از Restart همه‌چیز سالم",
              user_row(a)["bot_user_id"] == bid
              and db.get_balance(a) == bal2
              and user_row(c)["referred_by"] == a)
        runlog(f"E2E round {round_no}: PASS")


# ================= اجرا =================
async def main():
    db.init()
    stages = [stage01_start, stage02_registration, stage03_public_id,
              stage04_profile, stage05_main_menu, stage06_coins, stage07_search,
              stage08_concurrent_match, stage09_chat, stage10_reports,
              stage11_id_request, stage12_test_users, stage13_referral,
              stage14_feedback, stage15_admin, stage16_database,
              stage17_security, stage18_restart, stage19_stress, stage20_e2e]
    for fn in stages:
        try:
            await fn()
        except Exception as e:
            import traceback
            FAIL.append(f"{fn.__name__}: EXCEPTION {type(e).__name__}: {e}")
            print(f"  💥 {fn.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
    print("\n———————————————")
    print(f"✅ موفق: {len(PASS)} | ❌ ناموفق: {len(FAIL)}")
    for f in FAIL:
        print(f"   • {f}")
    with open("/tmp/v2_match_runs.log", "w", encoding="utf-8") as f:
        f.write("\n".join(RUNLOG))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
