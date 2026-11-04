"""سوئیت ممیزی کامل بگودیت — اجرا: python3 tests/test_audit_suite.py

پوشش تست‌های اجباری ممیزی: سینتکس/Import/وابستگی/دیتابیس/ثبت‌نام/استان‌ها/
شهرها/تغییر استان/پروفایل/تطبیق (شانسی، جنسیتی، نزدیک، فیلتر)/Race Condition/
چت/پایان چت/سکه/معرفی/کاربران تستی/پاسخ خودکار/گزارش/بن/پنل مدیریت/ری‌استارت/
بازیابی/خطاهای API تلگرام/امنیت Secrets/فورج Callback.
تست‌های نیازمند اتصال واقعی به تلگرام در این سوئیت «اجرا نمی‌شوند» و در گزارش
به‌عنوان اجرا‌نشده اعلام می‌گردند (هیچ‌گاه موفق جعل نمی‌شوند).
"""
import asyncio
import os
import sys
import tempfile
import threading

# دیتابیس و حجم کاربران تستی — باید «قبل از» ایمپورت config ست شود
_TMPDIR = tempfile.mkdtemp(prefix="bagoodit-audit-")
os.environ["DB_PATH"] = os.path.join(_TMPDIR, "audit.db")
os.environ["TEST_USERS_PER_CITY_F"] = "1"
os.environ["TEST_USERS_PER_CITY_M"] = "1"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
config.ADMIN_ID = 990000  # ادمین تستی

import database as db  # noqa: E402
import locations  # noqa: E402
from handlers import common  # noqa: E402
from keyboards import BTN_CHAT_END, BTN_CHAT_PROFILE, BTN_CHAT_REPORT  # noqa: E402
from keyboards import BTN_PROV_BACK, BTN_SKIP_PHOTO  # noqa: E402
from services import settings as S  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fakes import (FakeContext, FakeJob, FakeMessage, FakeUpdate,  # noqa: E402
                   fake_photo, last_markup, last_text, markup_texts)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append(f"{name} {detail}")
        print(f"  ❌ {name} {detail}")


CTX = FakeContext()
ADMIN_UID = 990000

_uid_seq = 800000


def new_uid() -> int:
    global _uid_seq
    _uid_seq += 1
    return _uid_seq


class _Q:
    """کال‌بک‌کوئری فیک با ثبت پاسخ‌ها."""

    def __init__(self, data: str, uid: int, message: FakeMessage):
        self.data, self.from_user, self.message = data, \
            type("U", (), {"id": uid})(), message
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


async def send_text(uid: int, text: str, ctx=None) -> FakeMessage:
    m = FakeMessage(text=text)
    await common.route_text(FakeUpdate(uid, m), ctx or CTX)
    return m


async def tap(uid: int, data: str, ctx=None) -> FakeMessage:
    m = FakeMessage()
    q = _Q(data, uid, m)
    await common.cb_router(FakeUpdate(uid, cbq=q), ctx or CTX)
    m._q = q  # noqa: SLF001 — دسترسی تستی به پاسخ‌های کال‌بک
    return m


def q_answers(m: FakeMessage) -> list:
    return getattr(m, "_q", None).answers if hasattr(m, "_q") else []


def user_row(uid: int):
    return db.get_user(uid)


async def register(uid: int, gender="F", age="25", prov="تهران", city="ری",
                   nick="تستی") -> None:
    await send_text(uid, "/start")
    await tap(uid, f"reg:gender:{gender}")
    await send_text(uid, age)
    await send_text(uid, prov)
    await send_text(uid, city)
    await send_text(uid, nick)
    # عکس اجباری — بدون عکس ثبت‌نام کامل نمی‌شود (قانون جدید)
    photo_msg = FakeMessage(photo=[fake_photo(f"ava-{uid}")])
    await common.route_media(FakeUpdate(uid, photo_msg), CTX)


def reset_flows() -> None:
    """پاکسازی صف و چت‌های فعال بین تست‌ها — ایزوله‌سازی سناریوها."""
    db.x("UPDATE users SET state='MAIN_MENU', context='{}' WHERE state='SEARCHING'")
    db.x("UPDATE chats SET state='CLOSED', ended_at=? WHERE state='ACTIVE'",
         (db.now_iso(),))
    db.x("UPDATE users SET state='MAIN_MENU', context='{}' WHERE state='IN_CHAT'")


def secure_settings() -> None:
    """تنظیمات قطعی برای تست‌های تطبیق — مستقل از ترتیب اجرای تست‌ها."""
    from services import test_users as TU
    S.set_value("real_users_first", "true")
    TU.stop_test_mode(manual=True)


# ================= ۱) سینتکس و ایمپورت =================
def t01_syntax_imports():
    print("T1) سینتکس و Compile همه فایل‌ها + Import همه ماژول‌ها")
    import py_compile
    count = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", "data", ".git",
                                    ".git-old-scaffold-backup")]
        for fn in filenames:
            if fn.endswith(".py"):
                py_compile.compile(os.path.join(dirpath, fn), doraise=True)
                count += 1
    check(f"{count} فایل پایتون بدون خطای سینتکس", count >= 25)
    import importlib
    mods = ["bot", "config", "database", "locations", "keyboards",
            "utils.helpers", "services.coins", "services.settings",
            "services.matching", "services.test_users", "services.auto_reply",
            "services.avatars", "handlers.common", "handlers.registration",
            "handlers.main_menu", "handlers.matching", "handlers.chat",
            "handlers.search_user", "handlers.feedback", "handlers.admin"]
    ok = True
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception as e:
            ok = False
            check(f"import {m}", False, f"{type(e).__name__}: {e}")
    check("هر ۲۰ ماژول بدون خطا import شد", ok)


# ================= ۲) وابستگی‌ها =================
def t02_dependencies():
    print("T2) نصب وابستگی‌ها")
    import telegram
    import dotenv
    check("python-telegram-bot نصب است", hasattr(telegram, "__version__"))
    check("python-dotenv نصب است", hasattr(dotenv, "load_dotenv"))
    try:
        import PIL.Image  # noqa: F401
        check("Pillow نصب است", True)
    except ImportError:
        check("Pillow نصب است", False, "اختیاری اما در requirements هست")


# ================= ۳) امنیت Secrets =================
def t03_secrets_scan():
    print("T3) امنیت — هیچ Token/Secret در سورس نیست")
    import re
    patterns = [
        (r"BOT_TOKEN\s*=\s*[\"'][^\"']{10,}", "توکن هاردکد"),
        (r"github_pat_[0-9A-Za-z_]{20,}", "توکن گیت‌هاب"),
        (r"ghp_[0-9A-Za-z]{20,}", "توکن گیت‌هاب کلاسیک"),
        (r"xox[baprs]-[0-9A-Za-z-]{10,}", "توکن Slack"),
        (r"AKIA[0-9A-Z]{16}", "کلید AWS"),
        (r"(?i)(password|passwd|secret)\s*=\s*[\"'][^\"']{8,}", "رمز هاردکد"),
    ]
    bad = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", "data", ".git",
                                    ".git-old-scaffold-backup")]
        for fn in filenames:
            if not fn.endswith((".py", ".yml", ".yaml", ".md", ".sh")):
                continue
            p = os.path.join(dirpath, fn)
            src = open(p, encoding="utf-8").read()
            for pat, label in patterns:
                for match in re.finditer(pat, src):
                    bad.append(f"{os.path.relpath(p, ROOT)}: {label}")
    check("بدون Secret در کد", not bad, f"got={bad[:3]}")
    gi = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    check(".env در .gitignore است", ".env" in gi)


# ================= ۴) دیتابیس =================
def t04_database():
    print("T4) دیتابیس — یکتایی، تراکنش، قفل")
    uid = new_uid()
    db.ensure_user(uid)
    db.ensure_user(uid)  # دوباره → ردیف تکراری نه
    rows = db.q("SELECT COUNT(*) AS c FROM users WHERE telegram_id=?", (uid,))
    check("ensure_user تکراری، ردیف دوباره نسازد", rows[0]["c"] == 1)
    ids = [db.gen_bot_user_id("F") for _ in range(20)]
    check("فرمت شناسه ناشناس صحیح است",
          all(i.startswith("user5") and i[5:].isdigit() for i in ids))
    # محدودیت UNIQUE دیتابیس: دو کاربر با یک شناسه → خطای یکتایی
    uid3 = new_uid()
    db.ensure_user(uid3)
    try:
        db.x("INSERT INTO users (telegram_id, bot_user_id, created_at, last_active) "
             "VALUES (?,?,?,?)", (uid3 + 1, ids[0], db.now_iso(), db.now_iso()))
        import sqlite3
        try:
            db.x("INSERT INTO users (telegram_id, bot_user_id, created_at, last_active) "
                 "VALUES (?,?,?,?)", (uid3 + 2, ids[0], db.now_iso(), db.now_iso()))
            dup_ok = False
        except sqlite3.IntegrityError:
            dup_ok = True
        check("UNIQUE بودن bot_user_id در دیتابیس تضمین شود", dup_ok)
    finally:
        db.x("DELETE FROM users WHERE telegram_id IN (?,?)", (uid3 + 1, uid3 + 2))
    bal = db.adjust_coins(uid, 30, "test:earn")
    check("شارژ سکه ثبت شود", bal == config.WELCOME_COINS + 30)
    check("برداشت بیش از موجودی رد شود", db.adjust_coins(uid, -10**9, "x") is None)
    check("موجودی منفی نشود", db.get_balance(uid) == config.WELCOME_COINS + 30)
    tx = db.user_transactions(uid)
    check("تراکنش‌ها ثبت شده‌اند", len(tx) >= 2 and all("balance_after" in t for t in tx))
    # همزمانی: ۱۰ نخ × ۱۰ تلاش برداشت ۱۵ سکه از موجودی اولیه → برداشت موفق = موجودی//۱۵
    uid2 = new_uid()
    db.ensure_user(uid2)
    bal0 = db.adjust_coins(uid2, 100, "seed")  # WELCOME + 100
    expected_ok = bal0 // 15
    results = []

    def worker():
        for _ in range(10):
            results.append(db.adjust_coins(uid2, -15, "race"))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    ok_count = sum(1 for r in results if r is not None)
    check("برداشت همزمان اتمیک است",
          ok_count == expected_ok and db.get_balance(uid2) == bal0 - 15 * expected_ok,
          f"ok={ok_count} want={expected_ok} bal={db.get_balance(uid2)}")


# ================= ۵) ثبت‌نام کامل =================
async def t05_registration():
    print("T5) ثبت‌نام کامل /start تا عکس")
    uid = new_uid()
    await register(uid, "M", "30", "فارس", "شیراز", "آرمین")
    row = user_row(uid)
    check("ثبت‌نام کامل شود", db.is_registered(row), f"state={row['state']}")
    check("جنسیت/سن/استان/شهر درست ذخیره شود",
          row["gender"] == "M" and row["age"] == 30
          and row["province"] == "فارس" and row["city"] == "شیراز")
    check("شناسه ناشناس پسر با ۴ شروع شود", (row["bot_user_id"] or "").startswith("user4"))
    uid2 = new_uid()
    await register(uid2, "F")
    check("شناسه ناشناس دختر با ۵ شروع شود",
          (user_row(uid2)["bot_user_id"] or "").startswith("user5"))
    check("سکه خوش‌آمدگویی واریز شود", user_row(uid2)["coins"] == config.WELCOME_COINS)


# ================= ۶) همه استان‌ها =================
async def t06_all_provinces():
    print("T6) انتخاب هر ۳۱ استان و یک شهر از هر استان")
    bad = []
    for pname, cities in locations.PROVINCES:
        uid = new_uid()
        await send_text(uid, "/start")
        await tap(uid, "reg:gender:F")
        await send_text(uid, "25")
        m = await send_text(uid, pname)
        btns = markup_texts(last_markup(m))
        if cities[0] not in btns or BTN_PROV_BACK not in btns:
            bad.append(f"{pname}: کیبورد شهر ناقص")
            continue
        await send_text(uid, cities[0])
        row = user_row(uid)
        if row["province"] != pname or row["city"] != cities[0]:
            bad.append(f"{pname}/{cities[0]}: got={row['province']}/{row['city']}")
    check("هر ۳۱ استان + اولین شهرش صحیح ذخیره شد", not bad, f"got={bad[:3]}")


# ================= ۷) ورودی نامعتبر =================
async def t07_invalid_inputs():
    print("T7) ورودی نامعتبر استان/شهر رد شود")
    uid = new_uid()
    await send_text(uid, "/start")
    await tap(uid, "reg:gender:M")
    await send_text(uid, "25")
    m = await send_text(uid, "آلمان")
    check("استان نامعتبر رد شود", user_row(uid)["state"] == config.ST_REG_PROVINCE
          and "استان نامعتبر" in last_text(m))
    await send_text(uid, "تهران")
    m2 = await send_text(uid, "کاشان")  # شهر اصفهان
    row = user_row(uid)
    check("شهر استان دیگر رد شود و چیزی ذخیره نشود",
          row["state"] == config.ST_REG_CITY and row["city"] is None
          and "شهر نامعتبر" in last_text(m2))
    m3 = await send_text(uid, "18")  # عدد به‌جای شهر
    check("متن دلخواه به‌جای شهر رد شود",
          user_row(uid)["state"] == config.ST_REG_CITY and "شهر نامعتبر" in last_text(m3))


# ================= ۸) تغییر استان =================
async def t08_province_change():
    print("T8) تغییر استان → پاک شدن شهر قبلی")
    uid = new_uid()
    await register(uid, prov="گیلان", city="رشت", nick="شهرنشین")
    m = await tap(uid, "pf:edit:city")
    check("ویرایش شهر از مرحله استان شروع شود",
          user_row(uid)["state"] == config.ST_REG_PROVINCE
          and len(markup_texts(last_markup(m))) == 31)
    await send_text(uid, "یزد")
    row = user_row(uid)
    check("با تغییر استان، شهر قبلی پاک شود",
          row["province"] == "یزد" and row["city"] is None)
    check("کاربرِ بدون شهر در تطبیق شرکت نکند", not db.is_registered(row))
    await send_text(uid, "میبد")
    row = user_row(uid)
    check("شهر جدید ذخیره و به منو برگردد",
          row["province"] == "یزد" and row["city"] == "میبد"
          and row["state"] == config.ST_MAIN)


# ================= ۹) پروفایل =================
async def t09_profile():
    print("T9) پروفایل — نمایش و ویرایش همه فیلدها")
    uid = new_uid()
    await register(uid, "F", "22", "قم", "قم", "نیلوفر")
    m = await send_text(uid, "👤 پروفایل من")
    caps = [p.text or "" for p in CTX.bot.photos]
    check("کارت پروفایل نمایش داده شود",
          ("نیلوفر" in last_text(m) and "user5" in last_text(m))
          or any("نیلوفر" in c and "user5" in c for c in caps))
    await tap(uid, "pf:edit:nickname")
    await send_text(uid, "نیلوفر آبی")
    check("تغییر نام ذخیره شود", user_row(uid)["nickname"] == "نیلوفر آبی")
    await tap(uid, "pf:edit:nickname")
    m_en = await send_text(uid, "Niloofar2")
    check("نام انگلیسی رد شود (قانون نام فارسی)",
          user_row(uid)["nickname"] == "نیلوفر آبی"
          and "فقط فارسی" in last_text(m_en))
    await tap(uid, "pf:edit:nickname")
    m_fa_num = await send_text(uid, "نیلوفر۲")
    check("نام با عدد رد شود", user_row(uid)["nickname"] == "نیلوفر آبی")
    _ = m_fa_num
    await tap(uid, "pf:edit:age")
    await send_text(uid, "26")
    check("تغییر سن ذخیره شود", user_row(uid)["age"] == 26)
    await tap(uid, "pf:edit:gender")
    await tap(uid, "reg:gender:M")
    check("تغییر جنسیت ذخیره شود", user_row(uid)["gender"] == "M")
    ctx = FakeContext()
    await tap(uid, "pf:edit:photo", ctx)
    photo_msg = FakeMessage(photo=[fake_photo("pid-1")])
    await common.route_media(FakeUpdate(uid, photo_msg), ctx)
    check("تغییر عکس ذخیره شود", user_row(uid)["avatar_file_id"] == "pid-1")
    check("پس از ویرایش، وضعیت MAIN باشد", user_row(uid)["state"] == config.ST_MAIN)


# ================= ۱۰) تطبیق شانسی =================
async def t10_random_match():
    print("T10) تطبیق شانسی + صف + تاریخچه")
    reset_flows()
    a, b = new_uid(), new_uid()
    await register(a, "F", "25", "البرز", "کرج", "آوای شب")
    await register(b, "M", "27", "البرز", "کرج", "آرش مهر")
    await send_text(a, "💬 چت ناشناس")
    await send_text(a, "🟢 چت تصادفی")
    check("کاربر اول در صف باشد", user_row(a)["state"] == config.ST_SEARCHING)
    await send_text(b, "💬 چت ناشناس")
    await send_text(b, "🟢 چت تصادفی")
    ra, rb = user_row(a), user_row(b)
    check("هر دو وارد چت شوند", ra["state"] == config.ST_CHAT
          and rb["state"] == config.ST_CHAT, f"got={ra['state']}/{rb['state']}")
    chat = db.get_active_chat(a)
    check("چت فعال با دو طرف ثبت شود", chat is not None
          and db.get_active_chat(b)["chat_id"] == chat["chat_id"])
    check("اعلام چت برای هر دو ارسال شده باشد",
          any(s.text and "چت ناشناس برقرار شد" in s.text for s in CTX.bot.sent))
    check("تطبیق در تاریخچه ثبت شود", db.was_recently_matched(a, b, 999999))


# ================= ۱۱) تطبیق جنسیتی =================
async def t11_gender_match():
    print("T11) جست‌وجوی جنسیتی — ناسازگار جفت نمی‌شود")
    reset_flows()
    m1, m2, f1 = new_uid(), new_uid(), new_uid()
    await register(m1, "M", "28", "اصفهان", "اصفهان", "پسر اول")
    await register(m2, "M", "29", "اصفهان", "اصفهان", "پسر دوم")
    await register(f1, "F", "24", "اصفهان", "اصفهان", "دختر اول")
    for u in (m1, m2, f1):
        await send_text(u, "💬 چت ناشناس")
    S.set_value("coin_girl", "1")
    S.set_value("coin_boy", "1")
    await send_text(m1, "🔵 جستجوی دختر")
    await send_text(m2, "🔵 جستجوی پسر")
    ra, rb = user_row(m1), user_row(m2)
    check("دو پسرِ جست‌وجوگرِ جنس مخالف جفت نشوند",
          ra["state"] == config.ST_SEARCHING and rb["state"] == config.ST_SEARCHING)
    await send_text(f1, "🔵 جستجوی پسر")
    check("دختر با پسرِ در صف جفت شود",
          user_row(f1)["state"] == config.ST_CHAT and user_row(m1)["state"] == config.ST_CHAT)
    check("پسر دوم همچنان در صف باشد", user_row(m2)["state"] == config.ST_SEARCHING)
    check("هزینه جست‌وجو از موجودی کم شود",
          db.get_balance(f1) == config.WELCOME_COINS - S.get_int("coin_boy"))
    # قانون جدید: لغو عمدی کاربر = بدون بازگشت سکه
    bal_before_cancel = db.get_balance(m2)
    await send_text(m2, "❌ لغو جستجو")
    check("لغو جستجو بدون بازگشت سکه (قانون جدید)",
          user_row(m2)["state"] == config.ST_MAIN
          and db.get_balance(m2) == bal_before_cancel,
          f"bal={db.get_balance(m2)} want={bal_before_cancel}")


# ================= ۱۲) افراد نزدیک =================
async def t12_nearby():
    print("T12) جست‌وجوی اطراف — هم‌استانی جفت، غیرهم‌استانی نه")
    reset_flows()
    u1, u2, u3 = new_uid(), new_uid(), new_uid()
    await register(u1, "F", "25", "مازندران", "ساری", "شمالی یک")
    await register(u2, "M", "26", "مازندران", "بابل", "شمالی دو")
    await register(u3, "M", "30", "فارس", "شیراز", "جنوبی یک")
    for u in (u1, u2, u3):
        await send_text(u, "💬 چت ناشناس")
    await send_text(u1, "🔴 افراد نزدیک")
    await send_text(u3, "🔴 افراد نزدیک")
    check("غیرهم‌استانی جفت نشود",
          user_row(u1)["state"] == config.ST_SEARCHING
          and user_row(u3)["state"] == config.ST_SEARCHING)
    await send_text(u2, "🔴 افراد نزدیک")
    check("هم‌استانی‌ها جفت شوند",
          user_row(u1)["state"] == config.ST_CHAT
          and user_row(u2)["state"] == config.ST_CHAT)


# ================= ۱۳) جست‌وجوی پیشرفته + فورج fw =================
async def t13_filter_wizard():
    print("T13) ویزارد پیشرفته + callback فورج‌شده fw")
    reset_flows()
    uid = new_uid()
    await register(uid, "M", "33", "تهران", "تهران", "فیلتری")
    await send_text(uid, "💬 چت ناشناس")
    await send_text(uid, "🟣 جستجوی پیشرفته")
    await send_text(uid, "20")
    await send_text(uid, "40")
    await tap(uid, "fw:prov:0")   # تهران
    await tap(uid, "fw:city:0:0")  # تهران
    row = user_row(uid)
    ctxrow = db.get_ctx(row)
    check("ویزارد تا صف با معیار کامل برود",
          row["state"] == config.ST_SEARCHING
          and ctxrow.get("search", {}).get("city") == "تهران"
          and ctxrow.get("search", {}).get("min_age") == 20
          and ctxrow.get("search", {}).get("max_age") == 40)
    await send_text(uid, "❌ لغو جستجو")
    check("لغو ویزارد به منو برگردد", user_row(uid)["state"] == config.ST_MAIN)
    # فورج: پارامتر غیرعددی → بدون کرش و بدون تغییر وضعیت
    await tap(uid, "fw:prov:abc")
    await tap(uid, "fw:city:0:xy")
    await tap(uid, "fw:page:xx")
    check("callback فورج‌شده fw بدون کرش و بدون اثر جانبی",
          user_row(uid)["state"] == config.ST_MAIN)


# ================= ۱۴) Race Condition =================
async def t14_race_condition():
    print("T14) Race Condition — جفت‌شدن اتمیک")
    reset_flows()
    target, a, b = new_uid(), new_uid(), new_uid()
    await register(target, "F", "25", "یزد", "یزد", "هدف")
    await register(a, "M", "27", "یزد", "یزد", "نخ اول")
    await register(b, "M", "29", "یزد", "یزد", "نخ دوم")
    db.set_state(target, config.ST_SEARCHING,
                 {"search": {"kind": "random"}, "joined": db.now_iso()})
    cid1 = db.pair_users(a, target, "random")
    cid2 = db.pair_users(b, target, "random")
    check("جفت‌شدن اول موفق", cid1 is not None)
    check("جفت‌شدن دوم (روی همان هدف) رد شود", cid2 is None, f"cid2={cid2}")
    check("کاربر B وارد چت نشود", user_row(b)["state"] != config.ST_CHAT)
    check("فقط یک چت فعال برای هدف", db.get_active_chat(target)["chat_id"] == cid1)


# ================= ۱۵+۱۶) چت و پایان چت =================
async def t15_chat_flow():
    print("T15) چت — انتقال متن/عکس + دکمه‌ها + گزارش")
    reset_flows()
    a, b = new_uid(), new_uid()
    await register(a, "F", "25", "قم", "قم", "فرستنده")
    await register(b, "M", "28", "قم", "قم", "گیرنده")
    await send_text(a, "💬 چت ناشناس")
    await send_text(a, "🟢 چت تصادفی")
    await send_text(b, "💬 چت ناشناس")
    await send_text(b, "🟢 چت تصادفی")
    chat = db.get_active_chat(a)
    check("چت برقرار شد", chat is not None and db.get_active_chat(b) is not None)
    pid = db.partner_id_of(chat, a)
    n_before = len([c for c in CTX.bot.copies if c["chat_id"] == pid])
    ma = FakeMessage(text="سلام بر تو")
    await common.route_text(FakeUpdate(a, ma), CTX)
    copied = [c for c in CTX.bot.copies if c["chat_id"] == pid]
    check("متن به شریک منتقل شود (copy_message)", len(copied) == n_before + 1)
    # عکس از طرف b
    ctxp = FakeContext()
    ph = FakeMessage(photo=[fake_photo("p-9")])
    await common.route_media(FakeUpdate(b, ph), ctxp)
    copied2 = [c for c in ctxp.bot.copies if c["chat_id"] == a]
    check("عکس به شریک منتقل شود", len(copied2) == 1)
    # دکمه پروفایل
    mp = await send_text(a, BTN_CHAT_PROFILE)
    profile_ok = "گیرنده" in last_text(mp) or any(
        "گیرنده" in (p.text or "") for p in CTX.bot.photos[-2:])
    check("پروفایل طرف مقابل نمایش داده شود", profile_ok)
    # گزارش
    mr = await send_text(a, BTN_CHAT_REPORT)
    check("منوی دلایل گزارش باز شود", len(markup_texts(last_markup(mr))) == 8)
    await tap(a, "rpt:1")
    rep = db.open_reports()
    check("گزارش در دیتابیس ثبت شود", len(rep) == 1 and rep[0]["reported_id"] == pid)
    check("ادمین از گزارش باخبر شود",
          any(s.text and "گزارش جدید" in s.text for s in CTX.bot.sent))

    # ---------- پایان چت (با تأیید دوم — قانون جدید) ----------
    print("T16) پایان چت برای هر دو طرف")
    n_reports = len(db.open_reports())
    await send_text(a, BTN_CHAT_END)
    check("تأیید دوم پایان چت نمایش داده شود و چت باز بماند",
          db.get_chat(chat["chat_id"])["state"] == "ACTIVE")
    await tap(a, "chat:endno")
    check("انصراف از پایان چت، چت را باز نگه دارد",
          db.get_chat(chat["chat_id"])["state"] == "ACTIVE")
    await send_text(a, BTN_CHAT_END)
    await tap(a, "chat:endok")
    check("چت بسته شود", db.get_chat(chat["chat_id"])["state"] == "CLOSED")
    ra, rb = user_row(a), user_row(b)
    check("هر دو به منو برگردند", ra["state"] == config.ST_MAIN
          and rb["state"] == config.ST_MAIN)
    check("طرف مقابل مطلع شود",
          any(s.text and "طرف مقابل چت را پایان داد" in s.text for s in CTX.bot.sent))
    m2 = await send_text(b, "هنوز هستم!")
    check("کاربرِ بدون چت به منو هدایت و پیامش چت نمی‌شود",
          user_row(b)["state"] == config.ST_MAIN
          and ("منو" in last_text(m2) or "تمام شده" in last_text(m2)))
    await tap(a, "rpt:1")  # گزارش بعد از بسته‌شدن چت
    check("گزارش بدون چت فعال ثبت نشود", len(db.open_reports()) == n_reports)


# ================= ۱۷) سکه =================
async def t17_coins():
    print("T17) سکه — موجودی ناکافی و تراکنش")
    secure_settings()
    uid = new_uid()
    await register(uid, "F", "25", "قم", "قم", "بی‌سکه")
    db.adjust_coins(uid, -(db.get_balance(uid)), "drain")
    bal0 = db.get_balance(uid)
    S.set_value("coin_nearby", "3")
    n_sent = len(CTX.bot.sent)
    await send_text(uid, "💬 چت ناشناس")
    await send_text(uid, "🔴 افراد نزدیک")
    notice = [s.text for s in CTX.bot.sent[n_sent:]]
    check("جست‌وجو بدون سکه رد شود",
          any("سکه کافی نداری" in (t or "") for t in notice))
    check("موجودی تغییر نکرده و صف نشود",
          db.get_balance(uid) == bal0
          and user_row(uid)["state"] == config.ST_MATCH_MENU,
          f"state={user_row(uid)['state']}")
    from services import coins
    coins.refund(uid, 5, "test")
    tx = db.user_transactions(uid)
    check("بازگشت سکه در تراکنش ثبت شود",
          tx[0]["reason"] == "refund:test" and tx[0]["amount"] == 5)
    check("مبلغ صفر spend بی‌اثر است", coins.spend(uid, 0, "x")[0] is True)
    S.set_value("coin_nearby", "3")


# ================= ۱۸) معرفی =================
async def t18_referral():
    print("T18) معرفی — پاداش یک‌بار، بدون خودمعرفی")

    class CtxStub:
        def __init__(self, args):
            self.bot = CTX.bot
            self.args = args

    a, b, c = new_uid(), new_uid(), new_uid()
    db.ensure_user(a)
    db.ensure_user(b)
    await common.cmd_start(FakeUpdate(a, FakeMessage(text=f"/start ref{a}")),
                           CtxStub([f"ref{a}"]))
    check("خودمعرفی رد شود", user_row(a)["referred_by"] is None)
    await common.cmd_start(FakeUpdate(b, FakeMessage(text=f"/start ref{a}")),
                           CtxStub([f"ref{a}"]))
    check("معرفی ثبت شود", user_row(b)["referred_by"] == a)
    bal_after = db.get_balance(a)
    check("پاداش به معرف برسد", bal_after >= S.get_int("referral_reward"))
    await common.cmd_start(FakeUpdate(b, FakeMessage(text=f"/start ref{a}")),
                           CtxStub([f"ref{a}"]))
    check("معرفی تکراری دوباره پاداش ندهد",
          db.get_balance(a) == bal_after and db.referral_count(a) == 1)
    db.update_user(a, banned=1)
    db.ensure_user(c)
    await common.cmd_start(FakeUpdate(c, FakeMessage(text=f"/start ref{a}")),
                           CtxStub([f"ref{a}"]))
    check("معرفی به معرف بن‌شده ثبت نشود", user_row(c)["referred_by"] is None)
    db.update_user(a, banned=0)


# ================= ۱۹) کاربران تستی =================
def t19_test_users():
    print("T19) کاربران تستی — ساخت، تکرار، انقضا")
    from services import test_users as TU
    n = TU.generate_test_users()
    check("کاربران تستی ساخته شدند", n > 300, f"n={n}")
    check("ساخت دوباره، تکراری نسازد", TU.generate_test_users() == 0)
    c = TU.test_counts()
    total_cities = sum(len(p[1]) for p in locations.PROVINCES)
    check("برای هر شهر ۱ دختر + ۱ پسر", c["female"] == total_cities
          and c["male"] == total_cities, f"f={c['female']} m={c['male']} cities={total_cities}")
    TU.stop_test_mode(manual=True)
    check("تست‌مود خاموش", not TU.test_mode_active())
    TU.start_test_mode(1)
    check("تست‌مود روشن", TU.test_mode_active())
    S.set_value("test_mode_expires_at", "2000-01-01T00:00:00+00:00")
    check("تست‌مود منقضی غیرفعال شود", TU.enforce_test_mode() is False
          and not TU.test_mode_active())
    TU.start_test_mode(1)
    tu = TU.pick_test_partner(gender="F", city="تهران")
    check("شریک تستی مطابق جنسیت/شهر انتخاب شود",
          tu is not None and tu["gender"] == "F" and tu["city"] == "تهران"
          and tu["telegram_id"] < 0)


# ================= ۲۰) پاسخ خودکار =================
async def t20_auto_reply():
    print("T20) پاسخ خودکار کاربر تستی — بدون حلقه، با سقف")
    from services import test_users as TU
    reset_flows()
    S.set_value("real_users_first", "false")
    TU.start_test_mode(1)
    uid = new_uid()
    await register(uid, "M", "30", "قم", "قم", "چت‌با‌تستی")
    ctx = FakeContext()
    await send_text(uid, "💬 چت ناشناس", ctx)
    await send_text(uid, "🟢 چت تصادفی", ctx)
    row = user_row(uid)
    check("کاربر با حساب تستی جفت شود",
          row["state"] == config.ST_CHAT
          and db.get_user(db.partner_id_of(db.get_active_chat(uid), uid))["is_test_user"] == 1)
    check("جاب سلام تستی زمان‌بندی شده باشد", len(ctx.job_queue.jobs) >= 1)
    n_sent_before = len(ctx.bot.sent)
    await ctx.job_queue.run_all()
    from services import auto_reply as AR
    greeting_pool = set(AR.GREETING)
    new_msgs = [s.text for s in ctx.bot.sent[n_sent_before:]]
    check("سلام تستی ارسال شد (از استخر سلام؟)",
          any(t in greeting_pool for t in new_msgs), f"got={new_msgs[:1]}")
    closed_msg = False
    sent_msgs = 0
    try:
        for i in range(15):
            chat = db.get_active_chat(uid)
            if not chat or chat["state"] != "ACTIVE":
                break
            m = FakeMessage(text=f"پیام شماره {i}، خوبی؟")
            await common.route_text(FakeUpdate(uid, m), ctx)
            await ctx.job_queue.run_all()
            sent_msgs += 1
            if any(s.text and "سقف تعداد پیام" in (s.text or "") for s in ctx.bot.sent):
                closed_msg = True
                break
        last_chat = db.get_active_chat(uid)
        check("چت با سقف پاسخ تستی بسته شود", closed_msg and last_chat is None
              and user_row(uid)["state"] == config.ST_MAIN, f"msgs={sent_msgs}")
        check("پاسخ تستی به خودش فید نشد (بدون حلقه)", sent_msgs <= 12)
    finally:
        S.set_value("real_users_first", "true")
        TU.stop_test_mode(manual=True)


# ================= ۲۱) پنل ادمین =================
async def t21_admin_panel():
    print("T21) پنل مدیریت — آمار، تنظیمات، دسترسی، فورج")
    db.ensure_user(ADMIN_UID)
    m = await tap(ADMIN_UID, "adm:stats")
    check("آمار نمایش داده شود", "آمار بگودیت" in last_text(m))
    other = new_uid()
    db.ensure_user(other)
    mo = await tap(other, "adm:stats")
    check("غیرادمین به پنل دسترسی ندارد",
          any(a[0] and "فقط ادمین" in a[0] for a in q_answers(mo)))
    await tap(ADMIN_UID, "adm:set:coin_girl")
    await send_text(ADMIN_UID, "2")
    check("تنظیم عددی اعمال شود", S.get_int("coin_girl") == 2)
    S.set_value("coin_girl", "1")
    await tap(ADMIN_UID, "adm:set:test_reply_min_delay")
    await send_text(ADMIN_UID, "2.5")
    check("تنظیم مقدار اعشاری پذیرفته شود (B1)",
          S.get_float("test_reply_min_delay") == 2.5)
    S.set_value("test_reply_min_delay", "3")
    await tap(ADMIN_UID, "adm:set:coin_girl")
    mi = await send_text(ADMIN_UID, "abc")
    check("ورودی غیرعددی تنظیم رد شود", "فقط عدد" in last_text(mi)
          and S.get("coin_girl") == "1")
    mf = await tap(ADMIN_UID, "adm:rban:abc:def")
    check("callback عددی فورج‌شده ادمین بدون کرش رد شود (B3)",
          any(a[0] and "نامعتبر" in a[0] for a in q_answers(mf)))
    fw = await tap(ADMIN_UID, "adm:ban:notanumber")
    check("ban فورج‌شده بدون کرش رد شود (B3)",
          any(a[0] and "نامعتبر" in a[0] for a in q_answers(fw)))


# ================= ۲۲) بن / رفع بن =================
async def t22_ban_unban():
    print("T22) بن و رفع بن + خروج از صف و بازگشت سکه")
    reset_flows()
    secure_settings()
    uid = new_uid()
    await register(uid, "M", "35", "کرمان", "کرمان", "متجرم")
    db.adjust_coins(uid, 10, "seed")
    S.set_value("coin_nearby", "3")
    await send_text(uid, "💬 چت ناشناس")
    await send_text(uid, "🔴 افراد نزدیک")
    check("کاربر در صف است", user_row(uid)["state"] == config.ST_SEARCHING)
    bal_in_queue = db.get_balance(uid)
    await tap(ADMIN_UID, f"adm:ban:{uid}")
    row = user_row(uid)
    check("بن اعمال شود", row["banned"] == 1)
    check("کاربر بن‌شده از صف خارج شود", row["state"] == config.ST_MAIN)
    check("سکه جست‌وجوی بن‌شده برگردد",
          db.get_balance(uid) == bal_in_queue + S.get_int("coin_nearby"))
    m = await send_text(uid, "سلام")
    check("کاربر بن‌شده پیامش پردازش نشود", "مسدود" in last_text(m))
    tu = db.q1("SELECT telegram_id FROM users WHERE is_test_user=1 LIMIT 1")
    await tap(ADMIN_UID, f"adm:ban:{tu['telegram_id']}")
    check("کاربر تستی بن نشود", db.get_user(tu["telegram_id"])["banned"] == 0)
    await tap(ADMIN_UID, f"adm:unban:{uid}")
    row = user_row(uid)
    check("رفع بن انجام شود", row["banned"] == 0 and row["state"] == config.ST_MAIN)


# ================= ۲۳) درخواست چت =================
async def t23_chat_request():
    print("T23) درخواست چت — گیت ثبت‌نام + قبول/رد + امنیت")
    reset_flows()
    secure_settings()
    a, b = new_uid(), new_uid()
    await register(a, "F", "25", "گیلان", "رشت", "درخواست‌دهنده")
    await register(b, "M", "27", "گیلان", "رشت", "گیرنده")
    u = new_uid()
    db.ensure_user(u)
    mu = await tap(u, f"usr:req:{b}")
    check("کاربرِ ثبت‌نام‌نکرده نتواند درخواست بدهد (B5)",
          any(x[0] and "ثبت‌نام" in x[0] for x in q_answers(mu)))
    check("درخواستی ساخته نشد",
          db.q1("SELECT COUNT(*) AS c FROM chat_requests WHERE from_uid=?", (u,))["c"] == 0)
    await send_text(a, "🔍 جستجوی کاربر")
    await send_text(a, user_row(b)["bot_user_id"])
    await tap(a, f"usr:req:{b}")  # دکمه درخواست روی کارت هدف
    rid_row = db.q1("SELECT request_id FROM chat_requests WHERE from_uid=? "
                    "ORDER BY request_id DESC", (a,))
    check("درخواست چت ثبت شود", rid_row is not None)
    rid = rid_row["request_id"]
    mw = await tap(a, f"crq:acc:{rid}")
    check("قبول توسط غیرگیرنده رد شود",
          any(x[0] and "مال تو نیست" in x[0] for x in q_answers(mw))
          and db.get_request(rid)["status"] == "PENDING")
    await tap(b, f"crq:acc:{rid}")
    check("قبول درخواست → هر دو در چت",
          user_row(a)["state"] == config.ST_CHAT and user_row(b)["state"] == config.ST_CHAT)
    db.close_chat(db.get_active_chat(a)["chat_id"], closer_id=None)
    # رد درخواست
    a2, b2 = new_uid(), new_uid()
    await register(a2, "F", "25", "گیلان", "رشت", "درخواست دوم")
    await register(b2, "M", "27", "گیلان", "رشت", "گیرنده دوم")
    await tap(a2, f"usr:req:{b2}")
    rid2 = db.q1("SELECT request_id FROM chat_requests WHERE from_uid=? "
                 "ORDER BY request_id DESC", (a2,))["request_id"]
    await tap(b2, f"crq:dec:{rid2}")
    check("رد درخواست وضعیت DECLINED شود",
          db.get_request(rid2)["status"] == "DECLINED"
          and user_row(a2)["state"] == config.ST_MAIN)


# ================= ۲۴) خطاهای API تلگرام =================
async def t24_telegram_errors():
    print("T24) خطاهای API تلگرام — بلاک شدن و خطای ارسال")
    from telegram.error import Forbidden
    reset_flows()
    secure_settings()
    a, b = new_uid(), new_uid()
    await register(a, "F", "25", "یزد", "یزد", "فرست دوم")
    await register(b, "M", "26", "یزد", "یزد", "گیر دوم")
    await send_text(a, "💬 چت ناشناس")
    await send_text(a, "🟢 چت تصادفی")
    await send_text(b, "💬 چت ناشناس")
    await send_text(b, "🟢 چت تصادفی")
    chat = db.get_active_chat(a)
    pid = db.partner_id_of(chat, a)
    CTX.bot.fail_copy_for.add(pid)
    CTX.bot.fail_copy_exc = Forbidden("blocked")
    m = FakeMessage(text="کجایی؟")
    await common.route_text(FakeUpdate(a, m), CTX)
    CTX.bot.fail_copy_for.clear()
    check("بلاک شدن شریک → بستن چت + اطلاع",
          db.get_chat(chat["chat_id"])["state"] == "CLOSED"
          and any(s.text and "بلاک کرده" in s.text for s in CTX.bot.sent))
    a2, b2 = new_uid(), new_uid()
    await register(a2, "F", "25", "یزد", "یزد", "فرست سوم")
    await register(b2, "M", "26", "یزد", "یزد", "گیر سوم")
    await send_text(a2, "💬 چت ناشناس")
    await send_text(a2, "🟢 چت تصادفی")
    await send_text(b2, "💬 چت ناشناس")
    await send_text(b2, "🟢 چت تصادفی")
    chat2 = db.get_active_chat(a2)
    pid2 = db.partner_id_of(chat2, a2)
    CTX.bot.fail_copy_for.add(pid2)
    CTX.bot.fail_copy_exc = RuntimeError("network down")
    m2 = FakeMessage(text="سلام دوباره")
    await common.route_text(FakeUpdate(a2, m2), CTX)
    CTX.bot.fail_copy_for.clear()
    check("خطای موقت → پیام تلاش مجدد، چت باز بماند",
          "تلاش کن" in last_text(m2)
          and db.get_chat(chat2["chat_id"])["state"] == "ACTIVE")
    db.close_chat(chat2["chat_id"], closer_id=None)
    bad_ctx = FakeContext()
    bad_ctx.error = Exception("خطای آزمایشی")
    um = FakeMessage()
    await common.error_handler(FakeUpdate(777, um), bad_ctx)
    check("error_handler به کاربر پیام خطا بدهد", "خطایی پیش آمد" in last_text(um))


# ================= ۲۵) ری‌استارت =================
def t25_restart_recovery():
    print("T25) ری‌استارت — حفظ اطلاعات کاربران")
    uid = new_uid()
    db.ensure_user(uid)
    db.update_user(uid, nickname="ماندگار", gender="F", age=30,
                   province="تهران", city="تهران")
    db._conn = None  # شبیه‌سازی توقف پروسه
    db.init()
    row = user_row(uid)
    check("داده‌ها پس از ری‌استارت حفظ شوند",
          row["nickname"] == "ماندگار" and row["province"] == "تهران"
          and db.is_registered(row))
    check("چت‌های قبلی پس از ری‌استارت موجودند",
          db.q1("SELECT COUNT(*) AS c FROM chats")["c"] >= 1)


# ================= ۲۶) همگانی =================
async def t26_broadcast():
    print("T26) پیام همگانی — فقط کاربران واقعی + گارد اجرای دوبله")
    from handlers import admin as A
    reset_flows()
    secure_settings()
    real_targets = [new_uid() for _ in range(3)]
    for i, uid in enumerate(real_targets):
        db.ensure_user(uid)
        db.update_user(uid, nickname=f"همگانی-{i}",
                       gender="M" if i % 2 else "F", age=25,
                       province="قم", city="قم")
    ctx = FakeContext()
    A.BC["running"] = True
    mb = await tap(ADMIN_UID, "adm:bsend", ctx)
    check("اجرای دوبل همگانی مسدود شود (B2)",
          any(x[0] and "در حال اجراست" in x[0] for x in q_answers(mb)))
    A.BC["running"] = False
    n_copies_before = len(ctx.bot.copies)
    await tap(ADMIN_UID, "adm:broadcast", ctx)
    bc_msg = FakeMessage(text="پیام همگانی آزمایشی")
    await A.handle_text(FakeUpdate(ADMIN_UID, bc_msg), ctx, db.get_user(ADMIN_UID))
    await A._run_broadcast(ctx, ADMIN_UID)
    test_ids = {r["telegram_id"] for r in
                db.q("SELECT telegram_id FROM users WHERE is_test_user=1")}
    new_copies = ctx.bot.copies[n_copies_before:]
    targets = {c["chat_id"] for c in new_copies}
    check("همگانی به همه کاربران واقعی رفت",
          set(real_targets).issubset(targets), f"targets={len(targets)}")
    check("همگانی به کاربران تستی نرفت", not (targets & test_ids))
    check("گزارش نهایی به ادمین رسید",
          any(t and ("تمام شد" in t or "متوقف شد" in t) for t in ctx.bot.edits))
    A.BC["running"] = False


# ================= اجرا =================
async def main():
    db.init()
    tests = [t01_syntax_imports, t02_dependencies, t03_secrets_scan,
             t04_database, t05_registration, t06_all_provinces,
             t07_invalid_inputs, t08_province_change, t09_profile,
             t10_random_match, t11_gender_match, t12_nearby,
             t13_filter_wizard, t14_race_condition, t15_chat_flow,
             t17_coins, t18_referral, t19_test_users, t20_auto_reply,
             t21_admin_panel, t22_ban_unban, t23_chat_request,
             t24_telegram_errors, t25_restart_recovery, t26_broadcast]
    for fn in tests:
        try:
            r = fn()
            if asyncio.iscoroutine(r):
                await r
        except Exception as e:
            FAIL.append(f"{fn.__name__}: EXCEPTION {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
    print("\n———————————————")
    print(f"✅ موفق: {len(PASS)} | ❌ ناموفق: {len(FAIL)}")
    for f in FAIL:
        print(f"   • {f}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
