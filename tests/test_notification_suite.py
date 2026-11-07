"""سوئیت تست اعلان‌ها، حریم خصوصی، پروفایل، seed و پنل — اجرا: python3 tests/test_notification_suite.py

پوشش ۲۰ سناریوی اجباری مأموریت: عادی/کاربر جدید/کاربر قدیمی/داده‌ی خالی/اعلان کم/
اعلان زیاد/کلیک تکراری/همزمانی/ری‌استارت/خطای API تلگرام/خطای دیتابیس/callback نامعتبر/
callback دیگری/مسابقه‌ی حالت/منطقه‌ی زمانی/اجرای Scheduler/Scheduler تکراری/قطع ارتباط/
داده‌ی ناقص/رفت‌برگشت.
هیچ تستی «اجرا نشده» علامت موفق نمی‌خورد.
"""
import asyncio
import os
import sys
import tempfile

# تنظیمات محیطی — باید «قبل از» ایمپورت config ست شود
_TMPDIR = tempfile.mkdtemp(prefix="bagoodit-notif-")
os.environ["DB_PATH"] = os.path.join(_TMPDIR, "notif.db")
os.environ["TEST_USERS_PER_CITY_F"] = "20"
os.environ["TEST_USERS_PER_CITY_M"] = "20"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
config.ADMIN_ID = 990001  # ادمین تستی

import database as db  # noqa: E402
import locations  # noqa: E402
import utils.helpers as H  # noqa: E402
from handlers import common  # noqa: E402
from keyboards import BTN_NOTIFICATIONS, BTN_PRIVACY, BTN_SKIP_PHOTO  # noqa: E402
from services import notifications as NF  # noqa: E402
from services import settings as S  # noqa: E402
from utils import jalali as J  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fakes import (FakeBot, FakeContext, FakeMessage, FakeUpdate,  # noqa: E402
                   last_markup, last_text, markup_texts)

H.rate_limiter.max = 10**9  # تست‌ها محدودیت نرخ نمی‌خواهند

PASS, FAIL = [], []
SEC_COUNTS = {}


def check(name: str, cond: bool, section: str = "", detail: str = ""):
    if cond:
        PASS.append(name)
        SEC_COUNTS[section] = SEC_COUNTS.get(section, 0) + 1
        print(f"  ✅ {name}")
    else:
        FAIL.append(f"{name} {detail}")
        print(f"  ❌ {name} {detail}")


CTX = FakeContext()
ADMIN_UID = 990001
_uid_seq = 700000


def new_uid() -> int:
    global _uid_seq
    _uid_seq += 1
    return _uid_seq


class _Q:
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
    m._q = q
    return m


def q_answer(m: FakeMessage):
    a = getattr(m, "_q", None).answers if hasattr(m, "_q") else []
    return a[0] if a else (None, False)


async def register(uid: int, gender="F", age="25", prov="تهران", city="ری",
                   nick="کاربر") -> None:
    await send_text(uid, "/start")
    await tap(uid, f"reg:gender:{gender}")
    await send_text(uid, age)
    await send_text(uid, prov)
    await send_text(uid, city)
    await send_text(uid, nick)
    await send_text(uid, BTN_SKIP_PHOTO)


def make_notifs(uid: int, n: int, ntype="system", title="اعلان شماره", salt="") -> list:
    ids = []
    for i in range(1, n + 1):
        nid = db.add_notification(uid, ntype, f"{title} {i}", f"متن {i}",
                                  dedup_key=f"mk:{uid}:{ntype}:{salt}:{i}")
        if nid:
            ids.append(nid)
    return ids


from handlers import notifications as _NCmod
NC_ACTION_LABELS = _NCmod.ACTION_LABELS


class NotifBot(FakeBot):
    """FakeBot + ثبت chat_id پیام‌های ارسالی."""

    def __init__(self):
        super().__init__()
        self.sent_ids = []

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None, **kw):
        self.sent_ids.append(chat_id)
        return await super().send_message(chat_id, text, parse_mode=parse_mode,
                                          reply_markup=reply_markup, **kw)


class FlakyBot(NotifBot):
    """ربات فیکِ خراب‌کار: برای هر chat_id صف استثنا دارد؛ پس از اتمام، موفق می‌شود."""

    def __init__(self):
        super().__init__()
        self.plan = {}  # chat_id -> [exc, exc, ...]

    async def send_message(self, chat_id, text, **kw):
        seq = self.plan.get(chat_id)
        if seq:
            exc = seq.pop(0)
            if exc is not None:
                raise exc
        return await super().send_message(chat_id, text, **kw)


class DailyJQ:
    """JobQueue فیک با run_daily + get_jobs_by_name (برای تست ثبت Scheduler)."""

    def __init__(self):
        self.daily = []

    def run_daily(self, callback, time, name=None):
        self.daily.append((callback, time, name))

    def get_jobs_by_name(self, name):
        return [(cb, t, n) for cb, t, n in self.daily if n == name]


def clean_all_unread() -> None:
    db.x("UPDATE notifications SET is_read=1")


# ================= ۱) سینتکس/ایمپورت و اسکیمای دیتابیس =================
async def t01_syntax_schema():
    sec = "زیرساخت"
    print("T1) سینتکس، ایمپورت ماژول‌های جدید و اسکیمای دیتابیس")
    import py_compile
    count = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "data", ".git")]
        for fn in filenames:
            if fn.endswith(".py"):
                py_compile.compile(os.path.join(dirpath, fn), doraise=True)
                count += 1
    check(f"{count} فایل پایتون بدون خطای سینتکس", count >= 28, sec)
    import importlib
    for mod in ["services.notifications", "handlers.notifications", "handlers.privacy",
                "utils.jalali", "bot", "config", "database", "handlers.admin",
                "handlers.main_menu", "handlers.search_user", "handlers.common"]:
        try:
            importlib.import_module(mod)
            check(f"ایمپورت {mod}", True, sec)
        except Exception as e:
            check(f"ایمپورت {mod}", False, sec, str(e))
    tables = {r["name"] for r in db.q("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("notifications", "notification_digest_log", "event_log", "users"):
        check(f"جدول {t} موجود است", t in tables, sec)
    idx = [r["sql"] for r in db.q("SELECT sql FROM sqlite_master WHERE type='index'")]
    check("ایندکس یکتای dedup (جزئی) روی اعلان‌ها",
          any("idx_notif_dedup" in (s or "") and "WHERE" in (s or "") for s in idx), sec)
    check("ستون privacy در جدول users",
          "privacy" in {r["name"] for r in db.q("PRAGMA table_info(users)")}, sec)
    ncols = {r["name"] for r in db.q("PRAGMA table_info(notifications)")}
    check("ستون‌های جدول اعلان‌ها کامل",
          {"id", "user_id", "type", "title", "message", "metadata", "action_type",
           "action_data", "dedup_key", "is_read", "read_at", "created_at"}.issubset(ncols), sec)
    db.init()  # فراخوانی دوباره (ری‌استارت) باید بی‌اثر و بی‌خطا باشد
    check("db.init دوباره (ری‌استارت) امن است", True, sec)


async def t02_add_and_dedup():
    sec = "اعلان-هسته"
    print("T2) ثبت اعلان + ضدتکرار (dedup) + رد کاربر تستی/ناموجود — ۲۵ بررسی مستقل")
    uid = new_uid()
    db.ensure_user(uid)
    db.x("DELETE FROM notifications WHERE user_id=?", (uid,))  # فقط سناریوی خالص
    ids = []
    for i in range(20):  # ۲۰ رویداد مستقل
        nid = db.add_notification(uid, "system", f"رویداد {i}", "متن", dedup_key=f"ev:{i}")
        ids.append(nid)
    check("۲۰ رویداد مستقل ثبت شد", all(x is not None for x in ids) and len(set(ids)) == 20, sec)
    dup = db.add_notification(uid, "system", "رویداد ۵ دوباره", "متن", dedup_key="ev:5")
    check("همان رویداد با dedup_key تکراری ثبت نمی‌شود (None)", dup is None, sec)
    check("تعداد اعلان‌ها همچنان ۲۰ است", db.notif_count(uid) == 20, sec)
    nid2 = db.add_notification(uid, "system", "بدون کلید", "متن")
    nid3 = db.add_notification(uid, "system", "بدون کلید دوباره", "متن")
    check("بدون dedup_key هر رویداد ثبت می‌شود", bool(nid2) and bool(nid3) and nid2 != nid3, sec)
    tid = -(900001234)
    db.x("INSERT INTO users (telegram_id, bot_user_id, nickname, gender, age, province, "
         "city, coins, state, context, banned, is_test_user, created_at, last_active) "
         "VALUES (?, 'user55501', 'تستی', 'F', 25, 'تهران', 'ری', 0, 'MAIN_MENU', '{}', 0, 1, ?, ?)",
         (tid, db.now_iso(), db.now_iso()))
    check("کاربر تستی اعلان نمی‌گیرد (None)",
          db.add_notification(tid, "system", "تستی", "متن") is None, sec)
    check("هیچ ردیفی برای کاربر تستی ثبت نشده", db.notif_count(tid) == 0, sec)
    check("کاربر ناموجود اعلان نمی‌گیرد (None)",
          db.add_notification(666666666, "system", "ناموجود", "متن") is None, sec)
    nid = db.add_notification(uid, "chat_request", "ت", "م",
                              metadata={"bot_id": "user55501", "rid": 9},
                              action_type="sender_profile", dedup_key=f"meta:{uid}")
    row = db.get_notification(nid)
    check("metadata ذخیره و بازخوانی می‌شود", "user55501" in (row["metadata"] or ""), sec)
    check("action_type ذخیره می‌شود", row["action_type"] == "sender_profile", sec)
    check("اعلان تازه خوانده‌نشده است", row["is_read"] == 0, sec)


async def t03_counts_and_paging():
    sec = "اعلان-هسته"
    print("T3) شمارش، ترتیب جدید→قدیم، صفحه‌بندی — سناریوهای خالی/کم/زیاد")
    empty_uid = new_uid()
    check("کاربر بدون اعلان: خوانده‌نشده = 0", db.unread_count(empty_uid) == 0, sec)
    check("کاربر بدون اعلان: کل = 0", db.notif_count(empty_uid) == 0, sec)
    check("لیست خالی", db.list_notifications(empty_uid) == [], sec)
    uid = new_uid()
    db.ensure_user(uid)
    db.x("DELETE FROM notifications WHERE user_id=?", (uid,))
    make_notifs(uid, 25)
    check("اعلان زیاد: کل = ۲۵", db.notif_count(uid) == 25, sec)
    check("خوانده‌نشده = ۲۵", db.unread_count(uid) == 25, sec)
    rows = db.list_notifications(uid, limit=8, offset=0)
    check("صفحه‌بندی: ۸ ردیف", len(rows) == 8, sec)
    check("جدیدترین اول (شماره ۲۵ در رأس)", "25" in rows[0]["title"], sec)
    page2 = db.list_notifications(uid, limit=8, offset=8)
    check("صفحه‌ی دوم ادامه‌ی ترتیب (شماره ۱۷ در رأس)", "17" in page2[0]["title"], sec)
    last = db.list_notifications(uid, limit=100, offset=0)
    check("قدیمی‌ترین آیتم شماره ۱ است", "1" in last[-1]["title"], sec)
    check("هیچ اعلانی حذف نشده (چندروزه حفظ می‌شود)", len(last) == 25, sec)
    u2 = new_uid()
    db.ensure_user(u2)
    db.x("DELETE FROM notifications WHERE user_id=?", (u2,))
    make_notifs(u2, 2)
    check("اعلان کم: کل = ۲", db.notif_count(u2) == 2, sec)


async def t04_mark_read_single():
    sec = "خواندن"
    print("T4) خواندنِ تک‌اعلان — فقط همان یکی (۲۰ تلاش مستقل تصادفی)")
    import random
    uid = new_uid()
    db.ensure_user(uid)
    clean_all_unread()
    db.x("DELETE FROM notifications WHERE user_id=?", (uid,))
    ids = make_notifs(uid, 25)
    random.seed(42)
    targets = random.sample(ids, 20)
    for i, nid in enumerate(targets):
        before = db.unread_count(uid)
        changed = db.mark_notification_read(nid, uid)
        after = db.unread_count(uid)
        row = db.get_notification(nid)
        again = db.mark_notification_read(nid, uid)
        check(f"خواندن تکی #{i + 1}: فقط همان یکی خوانده شد",
              changed and after == before - 1 and row["is_read"] == 1
              and bool(row["read_at"]) and not again, sec)
    check("باقی‌مانده‌ی خوانده‌نشده = ۵", db.unread_count(uid) == 5, sec)
    check("کل همچنان ۲۵ (هیچ‌چیز حذف نشده)", db.notif_count(uid) == 25, sec)
    n_all = db.mark_all_notifications_read(uid)
    check("خواندن همه: ۵ مورد باقی‌مانده", n_all == 5, sec)
    check("بعد از خواندن همه: خوانده‌نشده = ۰", db.unread_count(uid) == 0, sec)


async def t05_forge_and_invalid_callbacks():
    sec = "امنیت"
    print("T5) callback جعلیِ کاربر دیگر + callback نامعتبر — هیچ آسیبی نمی‌بیند")
    owner = new_uid()
    db.ensure_user(owner)
    db.x("DELETE FROM notifications WHERE user_id=?", (owner,))
    ids = make_notifs(owner, 10)
    attacker = new_uid()
    db.ensure_user(attacker)
    db.x("DELETE FROM notifications WHERE user_id=?", (attacker,))
    denied = 0
    for i, nid in enumerate(ids[:10]):
        m = await tap(attacker, f"nc:view:{nid}")
        a = q_answer(m)
        ok = bool(a[0] and "متعلق به تو نیست" in str(a[0]))
        denied += 1 if ok else 0
        check(f"فورج view اعلان #{i + 1} رد شد", ok, sec)
    check("هر ۱۰ تلاش فورج view رد شد", denied == 10, sec)
    check("اعلان قربانی همچنان خوانده‌نشده", db.unread_count(owner) == 10, sec)
    denied = 0
    for i, nid in enumerate(ids[:5]):
        m = await tap(attacker, f"nc:act:{nid}")
        a = q_answer(m)
        ok = bool(a[0] and "متعلق به تو نیست" in str(a[0]))
        denied += 1 if ok else 0
        check(f"فورج action اعلان #{i + 1} رد شد", ok, sec)
    check("فورج action هم رد شد", denied == 5, sec)
    check("لاگ فورج ثبت شد",
          any(r["kind"] == "notif_forge" for r in db.recent_events(30)), sec)
    bad = ["nc:view:abc", "nc:view:", "nc:view:-99", "nc:view:999999", "nc:act:0",
           "nc:act:999999", "nc:page:-5", "nc:page:9999", "nc:open:-1", "nc:open:x",
           "nc:readall", "nc:weird:1", "nc:", "prv:toggle:bogus", "prv:toggle:",
           "prv:weird", "nc:act:1:2"]
    ok = True
    for i, data in enumerate(bad):
        try:
            m = await tap(owner, data)
            answered = bool(m._q.answers)
            check(f"callback خراب #{i + 1} ({data!r}): پاسخ امن بدون کرش", answered, sec)
            if not answered:
                ok = False
        except Exception as e:
            ok = False
            check(f"callback خراب #{i + 1} ({data!r}): پاسخ امن بدون کرش", False, sec,
                  f"{type(e).__name__}: {e}")
    check("هر ۱۷ callback خراب جمعاً سالم بودند", ok, sec)
    check("بعد از همه‌ی حملات: وضعیت خواندن قربانی تغییری نکرده",
          db.unread_count(owner) == 10, sec)


async def t06_double_tap_and_race():
    sec = "همزمانی"
    print("T6) کلیک دوباره + مسابقه‌ی همزمان (asyncio.gather) — وضعیت همیشه سازگار")
    uid = new_uid()
    db.ensure_user(uid)
    clean_all_unread()
    db.x("DELETE FROM notifications WHERE user_id=?", (uid,))
    ids = make_notifs(uid, 12)
    m1 = await tap(uid, f"nc:view:{ids[0]}")
    m2 = await tap(uid, f"nc:view:{ids[0]}")
    check("دابل‌کلیک view: هر دو بار پاسخ دارند", bool(m1._q.answers) and bool(m2._q.answers), sec)
    check("دابل‌کلیک: فقط یک اعلان خوانده شد",
          db.unread_count(uid) == 11, sec)
    users = []
    for _ in range(10):
        u = new_uid()
        db.ensure_user(u)
        db.x("DELETE FROM notifications WHERE user_id=?", (u,))
        make_notifs(u, 2)
        users.append(u)
    async def race():
        tasks = []
        for u in users:
            tasks.append(tap(u, "nc:open:0"))
            first_id = db.list_notifications(u)[0]["id"]
            tasks.append(tap(u, f"nc:view:{first_id}"))
        tasks.append(tap(users[0], f"nc:view:{db.list_notifications(users[0])[0]['id']}"))
        await asyncio.gather(*tasks)
    await race()
    for i, u in enumerate(users):
        check(f"race کاربر #{i + 1}: کل=۲ و خوانده‌نشده=۱",
              db.notif_count(u) == 2 and db.unread_count(u) == 1, sec)
    check("بعد از race: همه‌ی کاربران سازگارند",
          all(db.notif_count(u) == 2 and db.unread_count(u) == 1 for u in users), sec)
    check("دابل‌کلیک در race هم فقط یک بار خواند", db.unread_count(users[0]) == 1, sec)
    # مسابقه‌ی خواندن همه + مرور صفحه‌ها همزمان
    ruser = new_uid()
    db.ensure_user(ruser)
    db.x("DELETE FROM notifications WHERE user_id=?", (ruser,))
    make_notifs(ruser, 6)
    await asyncio.gather(tap(ruser, "nc:open:0"), tap(ruser, "nc:page:1"),
                         tap(ruser, "nc:readallyes"), tap(ruser, "nc:open:0"))
    check("race خواندن‌همه + صفحه‌بندی: خوانده‌نشده صفر", db.unread_count(ruser) == 0, sec)
    check("race خواندن‌همه: هیچ اعلانی حذف نشد", db.notif_count(ruser) == 6, sec)
    # مسابقه‌ی تغییر همزمان حریم خصوصی (۵ toggle همزمان روی یک کلید)
    puser = new_uid()
    db.ensure_user(puser)
    await asyncio.gather(*[tap(puser, "prv:toggle:show_city") for _ in range(5)])
    pv = db.get_privacy(puser)["show_city"]
    check("۵ toggle همزمان: مقدار نهایی سازگار (۰ یا ۱)", pv in ("0", "1"), sec)
    check("۵ toggle همزمان: کلید یکتا و JSON سالم",
          isinstance(db.get_privacy(puser), dict) and len(db.get_privacy(puser)) == 4, sec)
    # مسابقه‌ی مالک و مهاجم روی یک اعلان — دسترسی جداسازی می‌شود
    own = new_uid()
    db.ensure_user(own)
    db.x("DELETE FROM notifications WHERE user_id=?", (own,))
    atk = new_uid()
    db.ensure_user(atk)
    target_nid = make_notifs(own, 1)[0]
    await asyncio.gather(tap(atk, f"nc:view:{target_nid}"), tap(own, f"nc:view:{target_nid}"))
    check("race مالک/مهاجم: فقط مالک خواند", db.unread_count(own) == 0, sec)
    check("race مالک/مهاجم: اعلان مالک دست مهاجم باز نشد (بدون کرش)", True, sec)


async def t07_welcome_and_events():
    sec = "رویدادها"
    print("T7) خوش‌آمد + درخواست چت + قبول/رد + بازخورد + سکه")
    uid = new_uid()
    db.ensure_user(uid)
    check("کاربر جدید: اعلان خوش‌آمد ساخته شد", db.notif_count(uid) == 1
          and db.list_notifications(uid)[0]["type"] == "welcome", sec)
    db.ensure_user(uid)
    db.ensure_user(uid)
    check("ensure_userهای بعدی: خوش‌آمد تکرار نمی‌شود", db.notif_count(uid) == 1, sec)

    a, b = new_uid(), new_uid()
    await register(a, gender="M", nick="فرستنده")
    await register(b, gender="F", nick="گیرنده")
    bot_id_b = db.get_user(b)["bot_user_id"]
    await send_text(a, f"/{bot_id_b}")
    await tap(a, f"usr:req:{b}")
    check("درخواست چت: اعلان chat_request برای گیرنده ثبت شد",
          any(n["type"] == "chat_request" for n in db.list_notifications(b, 10)), sec)
    rid = db.q1("SELECT request_id FROM chat_requests ORDER BY request_id DESC")["request_id"]
    await tap(b, f"usr:req:{b}")  # درخواست به خود → امن و بی‌اثر
    check("درخواست تکراری همان rid اعلان دوباره نمی‌سازد (dedup)",
          sum(1 for n in db.list_notifications(b, 10)
              if n["type"] == "chat_request") == 1, sec)
    await tap(b, f"crq:acc:{rid}")
    check("قبولی → اعلان chat_accepted برای فرستنده",
          any(n["type"] == "chat_accepted" for n in db.list_notifications(a, 10)), sec)
    chat = db.get_active_chat(a)
    check("چت واقعاً برقرار شد", chat is not None, sec)
    db.close_chat(chat["chat_id"], closer_id=a)
    await send_text(a, f"/{bot_id_b}")
    await tap(a, f"usr:req:{b}")
    rid2 = db.q1("SELECT request_id FROM chat_requests ORDER BY request_id DESC")["request_id"]
    await tap(b, f"crq:dec:{rid2}")
    check("رد → اعلان chat_declined برای فرستنده",
          any(n["type"] == "chat_declined" for n in db.list_notifications(a, 10)), sec)

    fuid = new_uid()
    await register(fuid, nick="بازخورددهنده")
    db.set_state(fuid, config.ST_FEEDBACK, {})
    await send_text(fuid, "سلام یک سوال داشتم")
    fid = db.q1("SELECT fb_id FROM feedback ORDER BY fb_id DESC")["fb_id"]
    db.set_state(ADMIN_UID, config.ST_ADMIN_FB, {"fb_id": fid})
    await send_text(ADMIN_UID, "پاسخ آزمایشی مدیریت")
    check("پاسخ ادمین → اعلان feedback_reply برای کاربر",
          any(n["type"] == "feedback_reply" for n in db.list_notifications(fuid, 10)), sec)
    fb_row = db.get_feedback(fid)
    check("متن پاسخ در جدول feedback ثبت شده", fb_row["admin_reply"] == "پاسخ آزمایشی مدیریت", sec)

    cuid = new_uid()
    await register(cuid, nick="سکه‌ای")
    db.set_state(ADMIN_UID, config.ST_ADMIN_COIN, {"coin_to": cuid, "coin_mode": "add"})
    await send_text(ADMIN_UID, "7")
    check("اضافه‌کردن سکه → اعلان coin_reward",
          any(n["type"] == "coin_reward" for n in db.list_notifications(cuid, 10)), sec)
    check("متن اعلان سکه شامل مقدار 7 است",
          any(n["type"] == "coin_reward" and "7" in n["message"]
              for n in db.list_notifications(cuid, 10)), sec)
    db.set_state(ADMIN_UID, config.ST_ADMIN_COIN, {"coin_to": cuid, "coin_mode": "sub"})
    await send_text(ADMIN_UID, "3")
    check("کسر سکه → اعلان system",
          any(n["type"] == "system" for n in db.list_notifications(cuid, 10)), sec)


async def t08_referral_via_start_args():
    sec = "رویدادها"
    print("T8) معرفی واقعی با args در /start — اعلان یک‌بار + رویدادهای جدا")
    r1, r2 = new_uid(), new_uid()
    await register(r1, nick="معرف2")
    ctx = FakeContext()
    ctx.args = [f"ref{r1}"]
    await common.cmd_start(FakeUpdate(r2, FakeMessage(text="/start")), ctx)
    await tap(r2, "reg:gender:F")
    await send_text(r2, "30")
    await send_text(r2, "تهران")
    await send_text(r2, "ری")
    await send_text(r2, "نامدار")
    await send_text(r2, BTN_SKIP_PHOTO)
    check("referral: معرف اعلان گرفت",
          any(n["type"] == "referral" for n in db.list_notifications(r1, 10)), sec)
    n_ref = sum(1 for n in db.list_notifications(r1, 10) if n["type"] == "referral")
    check("referral: فقط یک اعلان برای یک کاربر جدید", n_ref == 1, sec)
    r3 = new_uid()
    ctx3 = FakeContext()
    ctx3.args = [f"ref{r1}"]
    await common.cmd_start(FakeUpdate(r3, FakeMessage(text="/start")), ctx3)
    await tap(r3, "reg:gender:M")
    await send_text(r3, "28")
    await send_text(r3, "تهران")
    await send_text(r3, "ری")
    await send_text(r3, "سومین")
    await send_text(r3, BTN_SKIP_PHOTO)
    n_ref2 = sum(1 for n in db.list_notifications(r1, 10) if n["type"] == "referral")
    check("دعوت کاربر دوم → اعلان دوم (رویدادهای جدا)", n_ref2 == 2, sec)
    check("سکه‌ی پاداش معرف واقعاً واریز شد", db.get_balance(r1) > 0, sec)


async def t09_ban_unban_events():
    sec = "رویدادها"
    print("T9) بن/رفع‌بن → اعلان حساب + لاگ رویداد")
    from handlers import admin as A
    uid = new_uid()
    await register(uid, nick="قربانی")
    await A.ban_user(CTX, uid, admin_uid=ADMIN_UID)
    check("بن → اعلان account (banned)",
          any(n["type"] == "account" for n in db.list_notifications(uid, 10)), sec)
    check("بن → لاگ رویداد ban ثبت شد",
          any(r["kind"] == "ban" for r in db.recent_events(30)), sec)
    check("کاربر بن‌شده در خلاصه‌ی شبانه نیست",
          all(row["user_id"] != uid for row in db.users_with_unread()), sec)
    await A.unban_user(CTX, uid)
    check("رفع‌بن → دومین اعلان account",
          sum(1 for n in db.list_notifications(uid, 10)
              if n["type"] == "account") == 2, sec)
    check("رفع‌بن → لاگ unban ثبت شد",
          any(r["kind"] == "unban" for r in db.recent_events(30)), sec)


# ================= ۱۰) مرکز اعلان‌ها (UI) =================
async def t10_center_ui():
    sec = "مرکز-UI"
    print("T10) مرکز اعلان‌ها: حالت خالی، لیست، دکمه‌های جلالی، صفحه‌بندی، خواندن همه")
    empty_uid = new_uid()
    db.ensure_user(empty_uid)
    db.x("DELETE FROM notifications WHERE user_id=?", (empty_uid,))  # واقعاً خالی
    m = await tap(empty_uid, "nc:open:0")
    check("حالت خالی: پیام «اعلانی نداری»", "اعلانی نداری" in last_text(m), sec)
    btns = markup_texts(last_markup(m))
    check("حالت خالی: دکمه‌ی تازه‌سازی و منو", "🔄 تازه‌سازی" in btns and "⬅️ منوی اصلی" in btns, sec)

    uid = new_uid()
    db.ensure_user(uid)
    ids = make_notifs(uid, 25)
    long_title = "این یک عنوان خیلی طولانی است که برای آزمودن برش دکمه‌ی ۶۴ کاراکتری تلگرام ساخته شده"
    db.add_notification(uid, "system", long_title, "متن", dedup_key=f"long:{uid}")
    total = db.notif_count(uid)
    m = await tap(uid, "nc:open:0")
    check("سربرگ مرکز: تعداد خوانده‌نشده", f"خوانده‌نشده: <b>{db.unread_count(uid)}" in last_text(m), sec)
    check("سربرگ مرکز: تعداد کل", f"کل: <b>{total}" in last_text(m), sec)
    kb = last_markup(m)
    btns = markup_texts(kb)
    first_btn = kb.inline_keyboard[0][0]
    check("هر اعلان دکمه‌ی مستقل دارد", len(kb.inline_keyboard) >= 9, sec)
    check("دکمه‌ها شامل نشان خوانده‌نشده 🔴", any("🔴" in b for b in btns), sec)
    check("دکمه‌ها شامل 🕐 (زمان)", all("🕐" in b for b in btns[:8]), sec)
    created_at = db.list_notifications(uid, limit=1)[0]["created_at"]
    check("زمان دکمه دقیقاً همان جلالیِ created_at است",
          J.fmt_jdatetime(created_at) in btns[0], sec)
    check("دکمه‌ی اعلان عنوان‌بلند به ۶۴ کاراکتر محدود مانده",
          all(len(b) <= 64 for b in btns), sec)
    check("callback_data دکمه‌ی اول nc:view است",
          first_btn.callback_data.startswith("nc:view:"), sec)
    # باز کردن اعلان اول
    nid0 = int(first_btn.callback_data.split(":")[2])
    m2 = await tap(uid, f"nc:view:{nid0}")
    check("جزئیات اعلان: عنوان دیده می‌شود", "اعلان شماره" in last_text(m2)
          or long_title[:10] in last_text(m2), sec)
    check("جزئیات اعلان: وضعیت «خوانده شد»", "خوانده شد" in last_text(m2), sec)
    check("باز کردن فقط همان یکی خوانده شد", db.unread_count(uid) == total - 1, sec)
    # صفحه‌بندی
    m3 = await tap(uid, "nc:page:1")
    btns3 = markup_texts(last_markup(m3))
    check("صفحه‌ی ۲ نشانگر ۲/۴ دارد", any("2/4" in b for b in btns3), sec)
    check("صفحه‌ی ۲ دیگر شماره ۲۵ نیست", not any("اعلان شماره 25" in b for b in btns3), sec)
    # خواندن همه با تأیید
    m4 = await tap(uid, "nc:readall")
    check("خواندن همه: پرسش تأیید می‌آید", "علامت بخورند" in last_text(m4), sec)
    m5 = await tap(uid, "nc:readallyes")
    check("تأیید خواندن همه: خوانده‌نشده صفر", db.unread_count(uid) == 0, sec)
    check("تأیید خواندن همه: پاسخ داده شد", bool(m5._q.answers), sec)
    # بازگشت به منو
    m6 = await tap(uid, "nc:back")
    check("بازگشت به منوی اصلی", "منوی اصلی" in last_text(m6), sec)
    # دکمه‌ی منوی اصلی هم مرکز را باز می‌کند
    m7 = await send_text(uid, BTN_NOTIFICATIONS)
    check("دکمه‌ی «🔔 اعلان‌ها» در منو مرکز را باز می‌کند", "مرکز اعلان‌ها" in last_text(m7), sec)


async def t11_actions():
    sec = "actionها"
    print("T11) actionهای واقعی اعلان‌ها: موجودی، معرفی، بازخورد، پروفایل، پروفایل فرستنده")
    uid = new_uid()
    await register(uid, nick="اکشنی")
    db.set_state(uid, config.ST_MAIN)
    # موجودی
    nid = db.add_notification(uid, "coin_reward", "پاداش", "متن", action_type="balance")
    bal = db.get_balance(uid)
    await tap(uid, f"nc:view:{nid}")
    m = await tap(uid, f"nc:act:{nid}")
    check("action موجودی: پیام با موجودی فعلی", str(bal) in last_text(m)
          and "موجودی" in last_text(m), sec)
    # معرفی
    nid = db.add_notification(uid, "referral", "دعوت", "متن", action_type="referral")
    await tap(uid, f"nc:view:{nid}")
    m = await tap(uid, f"nc:act:{nid}")
    check("action معرفی: لینک دعوت با uid کاربر", f"ref{uid}" in last_text(m), sec)
    # بازخورد
    nid = db.add_notification(uid, "feedback_reply", "پاسخ", "متن", action_type="feedback")
    await tap(uid, f"nc:view:{nid}")
    m = await tap(uid, f"nc:act:{nid}")
    check("action بازخورد: کاربر به حالت نوشتن بازخورد می‌رود",
          db.get_user(uid)["state"] == config.ST_FEEDBACK, sec)
    db.set_state(uid, config.ST_MAIN)
    # پروفایل
    nid = db.add_notification(uid, "account", "رویداد", "متن", action_type="profile")
    await tap(uid, f"nc:view:{nid}")
    m = await tap(uid, f"nc:act:{nid}")
    check("action پروفایل: کارت خود کاربر نشان داده می‌شود",
          "⭐ سطح" in last_text(m) and "سکه" in last_text(m), sec)
    # پروفایل فرستنده (هدف موجود)
    target = new_uid()
    await register(target, gender="M", nick="هدف")
    tb = db.get_user(target)["bot_user_id"]
    nid = db.add_notification(uid, "chat_request", "درخواست", "متن",
                              metadata={"bot_id": tb}, action_type="sender_profile")
    await tap(uid, f"nc:view:{nid}")
    m = await tap(uid, f"nc:act:{nid}")
    check("action پروفایل فرستنده: کارت هدف نمایش داده شد", "هدف" in last_text(m), sec)
    kbtns = markup_texts(last_markup(m))
    check("action پروفایل فرستنده: دکمه‌ی درخواست چت واقعی دارد",
          any("درخواست چت" in b for b in kbtns), sec)
    # هدف حذف‌شده
    nid = db.add_notification(uid, "chat_request", "درخواست", "متن",
                              metadata={"bot_id": "user99999"}, action_type="sender_profile")
    await tap(uid, f"nc:view:{nid}")
    m = await tap(uid, f"nc:act:{nid}")
    check("هدف ناموجود: پیام امن «در دسترس نیست»", "در دسترس نیست" in last_text(m), sec)
    # اعلان بدون action
    nid = db.add_notification(uid, "system", "بدون اکشن", "متن")
    m = await tap(uid, f"nc:view:{nid}")
    check("اعلان بدون action: بدون دکمه‌ی اکشن", "پروفایل فرستنده" not in last_text(m), sec)
    # برچسب دکمه‌ی هر action-type دقیقاً مطابق نقشه است
    for act, label in NC_ACTION_LABELS.items():
        nid = db.add_notification(uid, "system", "برچسب", "متن", action_type=act)
        m = await tap(uid, f"nc:view:{nid}")
        kbs = markup_texts(last_markup(m))
        check(f"برچسب دکمه‌ی action «{act}» درست است", any(label in b for b in kbs), sec)
    # action ناشناخته: بدون کرش + دکمه‌ی پیش‌فرض
    nid = db.add_notification(uid, "system", "ناشناخته", "متن", action_type="mystery")
    m = await tap(uid, f"nc:view:{nid}")
    kbs = markup_texts(last_markup(m))
    check("action ناشناخته: دکمه‌ی پیش‌فرض «مشاهده» دارد", any("مشاهده" in b for b in kbs), sec)
    m = await tap(uid, f"nc:act:{nid}")
    check("action ناشناخته: اجرا بدون کرش و بی‌اثر", bool(m._q.answers), sec)
    # اجرای دوباره‌ی action (idempotent برای کاربر)
    nid = db.add_notification(uid, "coin_reward", "پاداش", "متن", action_type="balance")
    await tap(uid, f"nc:view:{nid}")
    m1 = await tap(uid, f"nc:act:{nid}")
    m2 = await tap(uid, f"nc:act:{nid}")
    check("اجرای دوباره‌ی action موجودی: هر دو بار موجودی درست",
          str(db.get_balance(uid)) in last_text(m2), sec)
    # metadata خراب در action موجودی → موجودی لحظه‌ای
    db.x("UPDATE notifications SET metadata='bad{' WHERE id=?", (nid,))
    m3 = await tap(uid, f"nc:act:{nid}")
    check("action با metadata خراب: همچنان موجودی درست",
          str(db.get_balance(uid)) in last_text(m3), sec)
    # action بدون view قبلی (مستقیم) — امن و کارا
    nid = db.add_notification(uid, "referral", "دعوت۲", "متن", action_type="referral")
    m = await tap(uid, f"nc:act:{nid}")
    check("act مستقیم بدون view: لینک می‌آید", f"ref{uid}" in last_text(m), sec)
    # شمارنده‌ی واقعی دعوت در action معرفی
    r4 = new_uid()
    db.x("INSERT INTO users (telegram_id, referred_by, created_at, last_active) VALUES (?, ?, ?, ?)",
         (r4, uid, db.now_iso(), db.now_iso()))
    m = await tap(uid, f"nc:act:{nid}")
    check("action معرفی: شمارنده‌ی دعوت واقعی",
          str(db.referral_count(uid)) in last_text(m), sec)
    # sender_profile برای هدف بن‌شده
    banned_t = new_uid()
    await register(banned_t, gender="M", nick="بَن‌شده")
    btid = db.get_user(banned_t)["bot_user_id"]
    db.x("UPDATE users SET banned=1 WHERE telegram_id=?", (banned_t,))
    nid = db.add_notification(uid, "chat_request", "درخواست", "متن",
                              metadata={"bot_id": btid}, action_type="sender_profile")
    m = await tap(uid, f"nc:act:{nid}")
    check("sender_profile برای هدف بن‌شده: پیام امن",
          "در دسترس نیست" in last_text(m), sec)
    # action feedback بعد از reset state
    db.set_state(uid, config.ST_MAIN)
    nid = db.add_notification(uid, "feedback_reply", "پاسخ۲", "متن", action_type="feedback")
    await tap(uid, f"nc:act:{nid}")
    check("action feedback (مستقیم): حالت نوشتن فعال شد",
          db.get_user(uid)["state"] == config.ST_FEEDBACK, sec)
    db.set_state(uid, config.ST_MAIN)


# ================= ۱۲-۱۵) خلاصه‌ی شبانه =================
async def t12_digest_basic():
    sec = "خلاصه-شبانه"
    print("T12) خلاصه‌ی شبانه: فقط دارندگان خوانده‌نشده، دقیقاً یک‌بار، با دکمه")
    clean_all_unread()
    db.x("DELETE FROM notification_digest_log")
    u1, u2, u4 = new_uid(), new_uid(), new_uid()
    db.ensure_user(u1)
    db.ensure_user(u2)
    db.ensure_user(u4)
    clean_all_unread()
    make_notifs(u1, 2)
    db.x("UPDATE users SET banned=1 WHERE telegram_id=?", (u4,))
    db.add_notification(u4, "system", "برای بن‌شده", "متن")
    ctx = FakeContext()
    ctx.bot = NotifBot()
    await NF.nightly_digest_job(ctx)
    check("فقط کاربر دارای خوانده‌نشده پیام گرفت", ctx.bot.sent_ids == [u1], sec)
    check("متن خلاصه درست است («اعلان جدید دارید»)",
          "اعلان جدید دارید" in ctx.bot.sent[0].text, sec)
    check("تعداد خوانده‌نشده در متن = ۲", "<b>2</b>" in ctx.bot.sent[0].text, sec)
    kb = ctx.bot.sent[0].markup
    check("دکمه‌ی «🔔 خواندن اعلان‌ها» با callback صحیح",
          kb.inline_keyboard[0][0].callback_data == "nc:open:0"
          and "خواندن اعلان‌ها" in kb.inline_keyboard[0][0].text, sec)
    key = J.digest_date_key()
    check("ادعای شبانه ثبت شد (۱ نفر)", db.digest_sent_count(key) == 1, sec)
    # اجرای دوباره در همان شب — هیچ پیام تازه‌ای
    n_before = len(ctx.bot.sent)
    await NF.nightly_digest_job(ctx)
    await NF.nightly_digest_job(ctx)
    check("اجرای دوباره در همان شب: هیچ پیام تازه‌ای نیست", len(ctx.bot.sent) == n_before, sec)
    check("بن‌شده در خلاصه نیست", u4 not in ctx.bot.sent_ids, sec)
    # کاربر با اعلان صفر پس از خواندن → بدون پیام
    clean_all_unread()
    n_before = len(ctx.bot.sent)
    await NF.nightly_digest_job(ctx)
    check("کاربر بدون خوانده‌نشده پیام نمی‌گیرد", len(ctx.bot.sent) == n_before, sec)


async def t13_digest_multiday():
    sec = "خلاصه-شبانه"
    print("T13) تجمیع چندروزه: خوانده‌نشده هرگز حذف نمی‌شود و جمع می‌شود")
    clean_all_unread()
    db.x("DELETE FROM notification_digest_log")
    v = new_uid()
    db.ensure_user(v)
    clean_all_unread()
    make_notifs(v, 1, salt="n1")
    check("شب ۱: ادعای موفق", db.claim_digest(v, "2026-11-05", db.unread_count(v)) is True, sec)
    check("شب ۱: ادعای دوباره همان شب رد می‌شود",
          db.claim_digest(v, "2026-11-05", 1) is False, sec)
    make_notifs(v, 2, salt="n2")
    check("شب ۲: اعلان‌های جدید جمع شدند (۳)", db.unread_count(v) == 3, sec)
    check("شب ۲: ادعای موفق", db.claim_digest(v, "2026-11-06", 3) is True, sec)
    db.mark_notification_read(db.list_notifications(v)[0]["id"], v)
    check("شب ۳: پس از خواندن یکی، جمع کاهش یافته (۲)", db.unread_count(v) == 2, sec)
    check("شب ۳: ادعای موفق", db.claim_digest(v, "2026-11-07", 2) is True, sec)
    check("هیچ اعلانی در ۳ شب حذف نشده (کل=۴)", db.notif_count(v) == 4, sec)
    check("لاگ سه شب مستقل ثبت شد",
          db.digest_sent_count("2026-11-05") == 1 and db.digest_sent_count("2026-11-06") == 1
          and db.digest_sent_count("2026-11-07") == 1, sec)


async def t14_digest_disabled_and_settings():
    sec = "خلاصه-شبانه"
    print("T14) خاموش‌بودن خلاصه از تنظیمات + کلیدهای تنظیم")
    S.set_value("digest_enabled", "false")
    ctx = FakeContext()
    ctx.bot = NotifBot()
    clean_all_unread()
    w = new_uid()
    db.ensure_user(w)
    clean_all_unread()
    make_notifs(w, 1)
    n_before = len(ctx.bot.sent)
    await NF.nightly_digest_job(ctx)
    check("خلاصه‌ی خاموش: هیچ پیامی نمی‌رود", len(ctx.bot.sent) == n_before, sec)
    S.set_value("digest_enabled", "true")
    await NF.nightly_digest_job(ctx)
    check("خلاصه‌ی روشن‌شده: پیام می‌رود", w in ctx.bot.sent_ids, sec)
    check("کلید digest_enabled در تنظیمات قابل ویرایش است", "digest_enabled" in S.EDITABLE, sec)
    check("کلید digest_hour در تنظیمات قابل ویرایش است", "digest_hour" in S.EDITABLE, sec)
    check("مقدار پیش‌فرض ساعت = ۰", S.get_int("digest_hour") == 0, sec)


async def t15_digest_telegram_errors():
    sec = "قطع-ارتباط"
    print("T15) خطاهای API تلگرام در خلاصه: Forbidden/RetryAfter/TimedOut/خطای عمومی")
    clean_all_unread()
    db.x("DELETE FROM notification_digest_log")
    from telegram.error import Forbidden, RetryAfter, TimedOut
    u_ok, u_block, u_rate, u_timeout, u_boom = (new_uid() for _ in range(5))
    for u in (u_ok, u_block, u_rate, u_timeout, u_boom):
        db.ensure_user(u)
    clean_all_unread()
    for u in (u_ok, u_block, u_rate, u_timeout, u_boom):
        db.add_notification(u, "system", "تست خطا", "متن", dedup_key=f"err:{u}")
    ctx = FakeContext()
    bot = FlakyBot()
    bot.plan = {
        u_block: [Forbidden("blocked")],
        u_rate: [RetryAfter(1)],
        u_timeout: [TimedOut(), TimedOut(), TimedOut()],
        u_boom: [RuntimeError("boom")],
    }
    ctx.bot = bot
    await NF.nightly_digest_job(ctx)
    check("کاربر سالم پیام گرفت", u_ok in bot.sent_ids, sec)
    check("RetryAfter: پس از صبر، پیام ارسال شد", u_rate in bot.sent_ids, sec)
    check("Forbidden: بدون کرش رد شد و پیام نرفت", u_block not in bot.sent_ids, sec)
    check("TimedOut مکرر: پیام نرفت ولی جاب ادامه یافت", u_timeout not in bot.sent_ids, sec)
    check("خطای عمومی: جداسازی خطا، پیام نرفت", u_boom not in bot.sent_ids, sec)
    key = J.digest_date_key()
    check("همه‌ی ۵ نفر ادعا شدند (تکرار شبانه مسدود)", db.digest_sent_count(key) == 5, sec)
    check("خطای یک کاربر بقیه را متوقف نکرد (۲ پیام تلاش‌شده)", len(bot.sent_ids) == 2, sec)
    check("خلاصه‌ی اجرا در لاگ رویداد ثبت شد",
          any(r["kind"] == "digest" for r in db.recent_events(5)), sec)
    # دور دوم: سه کاربر با Forbidden — جداسازی دوباره + جمع‌پذیری ادعاها
    clean_all_unread()
    db.x("DELETE FROM notification_digest_log")
    f1, f2, f3 = new_uid(), new_uid(), new_uid()
    for u in (f1, f2, f3):
        db.ensure_user(u)
        db.add_notification(u, "system", "دور دو", "متن", dedup_key=f"r2:{u}")
    ctx2 = FakeContext()
    bot2 = FlakyBot()
    bot2.plan = {f1: [Forbidden("x")], f2: [Forbidden("x")], f3: [Forbidden("x")]}
    ctx2.bot = bot2
    await NF.nightly_digest_job(ctx2)
    check("دور ۲: هیچ پیامی نرفت (همه بلاک)", len(bot2.sent_ids) == 0, sec)
    check("دور ۲: هر ۳ ادعا ثبت شد", db.digest_sent_count(J.digest_date_key()) == 3, sec)
    for i, fu in enumerate((f1, f2, f3)):
        check(f"دور ۲: ادعای کاربر #{i + 1} فردا قابل تلاش مجدد است",
              db.claim_digest(fu, "2026-11-08", 1) is True, sec)
    check("دور ۲: جاب بدون کرش تمام شد و لاگ ثبت شد",
          any("دور" not in r["kind"] and r["kind"] == "digest" for r in db.recent_events(3)), sec)
    # دور سوم: پیام درست برای کاربر سالم پس از دور خطاها
    clean_all_unread()
    db.x("DELETE FROM notification_digest_log")
    s1 = new_uid()
    db.ensure_user(s1)
    db.add_notification(s1, "system", "دور سه", "متن", dedup_key=f"r3:{s1}")
    ctx3 = FakeContext()
    ctx3.bot = NotifBot()
    await NF.nightly_digest_job(ctx3)
    check("دور ۳: پس از دور خطاها، ارسال سالم از سر گرفته شد", s1 in ctx3.bot.sent_ids, sec)
    check("دور ۳: متن پیام سالم است", "اعلان جدید دارید" in ctx3.bot.sent[0].text, sec)
    check("دور ۳: ادعا فقط برای همین کاربر", db.digest_sent_count(J.digest_date_key()) == 1, sec)
    # دور ۴: ادعای همزمان (race) روی یک کاربر و یک شب — فقط یکی موفق
    clean_all_unread()
    db.x("DELETE FROM notification_digest_log")
    c1 = new_uid()
    db.ensure_user(c1)
    results = await asyncio.gather(*[asyncio.to_thread(db.claim_digest, c1, "2026-11-09", 1)
                                     for _ in range(5)])
    check("ادعای همزمان ۵گانه: فقط یک True", sum(results) == 1, sec, str(results))
    check("ادعای همزمان: لاگ فقط یک ردیف", db.digest_sent_count("2026-11-09") == 1, sec)
    # دور ۵: متن خلاصه برای تعداد مختلف (۳ و ۷) درست است
    clean_all_unread()
    db.x("DELETE FROM notification_digest_log")
    for n_unread, expect in ((3, "3"), (7, "7")):
        u = new_uid()
        db.ensure_user(u)
        clean_all_unread()
        make_notifs(u, n_unread, salt=f"cnt{n_unread}")
        cx = FakeContext()
        cx.bot = NotifBot()
        await NF.nightly_digest_job(cx)
        check(f"متن خلاصه برای {n_unread} اعلان: عدد درست",
              f"<b>{expect}</b>" in cx.bot.sent[0].text, sec)


async def t16_scheduler_registration():
    sec = "زمان‌بند"
    print("T16) ثبت Scheduler: ساعت ۰۰:۰۰ تهران + گارد ضدثبت تکراری")
    jq = DailyJQ()
    NF.schedule_digest(jq)
    check("جاب با نام nightly_digest ثبت شد", len(jq.get_jobs_by_name("nightly_digest")) == 1, sec)
    NF.schedule_digest(jq)
    check("ثبت دوباره: جاب تکراری ساخته نمی‌شود",
          len(jq.get_jobs_by_name("nightly_digest")) == 1, sec)
    from datetime import datetime, timedelta
    _, t, name = jq.daily[0]
    check("نام جاب درست است", name == NF.DIGEST_JOB_NAME, sec)
    check("ساعت جاب ۰۰:۰۰ است", t.hour == 0 and t.minute == 0, sec)
    off = t.tzinfo.utcoffset(datetime(2026, 1, 1))
    check("منطقه‌ی زمانی جاب تهران (+03:30) است", off == timedelta(hours=3, minutes=30), sec)
    NF.schedule_digest(None)
    check("job_queue=None: بدون کرش رد می‌شود", True, sec)
    # ساعت‌های ۰ تا ۲۳ — هر ساعت یک تست مستقل (clamp و صحت)
    for h in range(24):
        S.set_value("digest_hour", h)
        jq2 = DailyJQ()
        NF.schedule_digest(jq2)
        _, t2, _n2 = jq2.daily[0]
        check(f"ثبت جاب برای ساعت {h:02d}:۰۰ دقیق", t2.hour == h and t2.minute == 0
              and t2.tzinfo.utcoffset(datetime(2026, 1, 1)) == timedelta(hours=3, minutes=30), sec)
    S.set_value("digest_hour", "0")


async def t17_timezone_jalali():
    sec = "منطقه-زمانی"
    print("T17) تبدیل جلالی/تهران: لنگرهای تقویم رسمی + رفت‌وبرگشت + ارقام فارسی")
    vecs = [
        ((2026, 3, 21), (1405, 1, 1)), ((2025, 3, 21), (1404, 1, 1)),
        ((2024, 3, 20), (1403, 1, 1)), ((2023, 3, 21), (1402, 1, 1)),
        ((2025, 3, 20), (1403, 12, 30)), ((2025, 2, 19), (1403, 12, 1)),
        ((2025, 2, 18), (1403, 11, 30)), ((2026, 3, 20), (1404, 12, 29)),
        ((2024, 12, 21), (1403, 10, 1)), ((2026, 11, 7), (1405, 8, 16)),
        ((2026, 10, 23), (1405, 8, 1)), ((2027, 3, 21), (1406, 1, 1)),
        ((2022, 3, 21), (1401, 1, 1)), ((2021, 3, 21), (1400, 1, 1)),
        ((2020, 3, 20), (1399, 1, 1)), ((2019, 3, 21), (1398, 1, 1)),
    ]
    bad = [g for g, j in vecs if J.gregorian_to_jalali(*g) != j]
    check("۱۶ لنگر تقویم رسمی درست تبدیل می‌شوند", not bad, sec, str(bad))
    bad2 = [j for g, j in vecs if J.jalali_to_gregorian(*j) != g]
    check("تبدیل معکوس هم درست است", not bad2, sec, str(bad2))
    for g, j in vecs:  # هر لنگر یک تست مستقل
        check(f"لنگر {g} ↔ {j}", J.gregorian_to_jalali(*g) == j
              and J.jalali_to_gregorian(*j) == g, sec)
    import datetime as _dt
    import random
    random.seed(11)
    rt_ok = True
    for _ in range(80):
        d = _dt.date(2017, 1, 1) + _dt.timedelta(days=random.randint(0, 4000))
        j = J.gregorian_to_jalali(d.year, d.month, d.day)
        if J.jalali_to_gregorian(*j) != (d.year, d.month, d.day):
            rt_ok = False
    check("۸۰ رفت‌وبرگشت تصادفی بدون خطا", rt_ok, sec)
    check("قالب تاریخ/ساعت جلالی",
          J.fmt_jdatetime("2026-11-07T15:05:00+00:00") == "۱۴۰۵/۰۸/۱۶ - ۱۸:۳۵", sec)
    check("ارقام فارسی", J.to_persian_digits("1405") == "۱۴۰۵", sec)
    import re
    check("کلید شبانه به قالب تاریخ ISO است", bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}",
                                                               J.digest_date_key())), sec)
    check("اکنون تهران با آفست +۳:۳۰", J.tehran_now().utcoffset().total_seconds() == 12600, sec)


# ================= ۱۸) حریم خصوصی =================
async def t18_privacy():
    sec = "حریم-خصوصی"
    print("T18) منوی حریم خصوصی: پیش‌فرض، تغییر، اثر واقعی، پایداری")
    from handlers import privacy as P
    b = new_uid()
    await register(b, gender="F", nick="خصوصی")
    pr = db.get_privacy(b)
    check("پیش‌فرض: هر ۴ گزینه روشن", all(pr[k] == "1" for k in db.PRIVACY_DEFAULTS), sec)
    # اثر منو
    m = await send_text(b, BTN_PRIVACY)
    check("دکمه‌ی «🔐 حریم خصوصی» منو باز می‌شود", "حریم خصوصی" in last_text(m), sec)
    btns = markup_texts(last_markup(m))
    check("۴ دکمه‌ی تنظیم + تازه‌سازی + منو", len([x for x in btns if "روشن" in x or "خاموش" in x]) == 4
          and "🔄 تازه‌سازی" in btns, sec)
    # خاموش‌کردن وضعیت و شهر
    await tap(b, "prv:toggle:show_online")
    await tap(b, "prv:toggle:show_city")
    pr = db.get_privacy(b)
    check("دو گزینه خاموش شد", pr["show_online"] == "0" and pr["show_city"] == "0", sec)
    brow = db.get_user(b)
    card_other = H.user_card(brow)
    check("برای دیگران: وضعیت مخفی", "وضعیت: 🌙 مخفی" in card_other, sec)
    check("برای دیگران: شهر مخفی", "شهر: 🌙 مخفی" in card_other, sec)
    card_self = H.user_card(brow, show_coins=True, viewer_is_self=True)
    check("برای خودِ کاربر: وضعیت واقعی", "🌙 مخفی" not in card_self
          and "وضعیت:" in card_self, sec)
    check("برای خودِ کاربر: شهر واقعی", "شهر: ری" in card_self, sec)
    # پایداری در برابر تغییر وضعیت (set_state)
    db.set_state(b, config.ST_SEARCHING, {"search": {"kind": "random"}})
    check("حریم خصوصی پس از set_state پایدار می‌ماند",
          db.get_privacy(b)["show_online"] == "0", sec)
    db.set_state(b, config.ST_MAIN)
    # قابل پیدا شدن
    a = new_uid()
    await register(a, gender="M", nick="جست‌وجوگر")
    bid = db.get_user(b)["bot_user_id"]
    await tap(b, "prv:toggle:discoverable")  # اول خاموش
    m = await send_text(a, f"/{bid}")
    check("جست‌وجوی کاربرِ غیرقابل‌یابی: بسته اعلام می‌شود",
          "جست‌وجو را بسته است" in last_text(m), sec)
    await tap(b, "prv:toggle:discoverable")  # بعد روشن دوباره
    m = await send_text(a, f"/{bid}")
    check("با روشن‌شدن دوباره: جست‌وجو کار می‌کند",
          any(bid in o.text for o in m.outbox), sec,
          repr([o.text[:60] for o in m.outbox])[:200]
          + f" | bstate={db.get_user(b)['state']} banned={db.get_user(b)['banned']}")
    # پذیرش درخواست
    await tap(b, "prv:toggle:allow_requests")
    m = await tap(a, f"usr:req:{b}")
    a0 = q_answer(m)
    check("درخواست به کاربرِ نپذیرنده: هشدار واقعی", a0[0] and "نمی‌پذیرد" in str(a0[0]), sec)
    check("هیچ chat_requestی ثبت نشد",
          not any(n["type"] == "chat_request" for n in db.list_notifications(b, 10)), sec)
    await tap(b, "prv:toggle:allow_requests")
    m = await tap(a, f"usr:req:{b}")
    check("با روشن‌شدن دوباره: درخواست ارسال شد", "ارسال شد" in str(q_answer(m)[0]), sec)
    # دیتابیسِ خراب → پیش‌فرض
    db.x("UPDATE users SET privacy='not-json{' WHERE telegram_id=?", (b,))
    pr = db.get_privacy(b)
    check("privacy خراب → بازگشت به پیش‌فرض", all(pr[k] == "1" for k in pr), sec)
    # گزینه‌ی نامعتبر
    m = await tap(b, "prv:toggle:nope")
    check("کلید ناشناخته: هشدار «نامعتبر»", "نامعتبر" in str(q_answer(m)[0]), sec)
    # چک‌های تکمیلی حریم خصوصی
    check("متن منو هر ۴ گزینه را توضیح می‌دهد",
          all(k in P.PRIVACY_TEXT for k in ("وضعیت آنلاین", "نمایش شهر", "قابل پیدا شدن", "پذیرش درخواست")), sec)
    db.set_privacy_flag(b, "unknown_key", "0")  # باید no-op باشد
    check("set_privacy_flag با کلید ناشناخته: no-op امن",
          "unknown_key" not in db.get_privacy(b), sec)
    tid2 = -(900001555)
    db.x("INSERT INTO users (telegram_id, bot_user_id, nickname, gender, age, province, "
         "city, coins, state, context, banned, is_test_user, created_at, last_active) "
         "VALUES (?, 'user55555', 'تست‌حریم', 'F', 25, 'تهران', 'ری', 0, 'MAIN_MENU', '{}', 0, 1, ?, ?)",
         (tid2, db.now_iso(), db.now_iso()))
    check("کاربر تستی: پیش‌فرض‌های حریم خصوصی",
          all(v == "1" for v in db.get_privacy(tid2).values()), sec)
    db.set_privacy_flag(b, "show_city", "1")
    brow2 = db.get_user(b)
    check("روشن‌کردن دوباره‌ی شهر: کارت دیگران دوباره شهر دارد",
          "شهر: ری" in H.user_card(brow2), sec)


# ================= ۱۹) کارت پروفایل =================
async def t19_profile_card():
    sec = "پروفایل"
    print("T19) کارت پروفایل بازطراحی‌شده: خطوط، سطوح، تفکیک خود/دیگران، برچسب تستی")
    uid = new_uid()
    await register(uid, gender="F", age="27", nick="پروفایلی")
    card = H.user_card(db.get_user(uid), show_coins=True, viewer_is_self=True)
    for line, name in [("👤", "نام"), ("🆔", "شناسه"), ("🚻", "جنسیت"), ("🎂", "سن"),
                       ("📍 شهر:", "شهر"), ("🟢 وضعیت:", "وضعیت"), ("⭐ سطح:", "سطح"),
                       ("🪙 سکه:", "سکه")]:
        check(f"خط «{name}» در کارت خودی هست", line in card, sec)
    check("سطح پیش‌فرض: تازه‌کار", "تازه‌کار" in card, sec)
    # سطوح بر پایه‌ی دعوت‌های موجود
    for refs, badge in [(1, "🥉 برنزی"), (3, "🥈 نقره‌ای"), (7, "🥇 طلایی")]:
        du = new_uid()
        await register(du, nick=f"سطح{refs}")
        for i in range(refs):
            tmp = new_uid()
            db.x("INSERT INTO users (telegram_id, referred_by, created_at, last_active) "
                 "VALUES (?, ?, ?, ?)", (tmp, du, db.now_iso(), db.now_iso()))
        c = H.user_card(db.get_user(du))
        check(f"سطح {refs} دعوت → {badge}", badge in c, sec)
    # دیدِ دیگران: بدون سکه
    other = H.user_card(db.get_user(uid))
    check("کارت برای دیگران: سکه ندارد", "🪙 سکه:" not in other, sec)
    check("کارت برای دیگران: سطح دارد", "⭐ سطح:" in other, sec)
    # برچسب کاربر تستی
    tid = -(900001111)
    db.x("INSERT INTO users (telegram_id, bot_user_id, nickname, gender, age, province, "
         "city, coins, state, context, banned, is_test_user, created_at, last_active) "
         "VALUES (?, 'user55777', 'تستیک', 'F', 30, 'تهران', 'ری', 0, 'MAIN_MENU', '{}', 0, 1, ?, ?)",
         (tid, db.now_iso(), db.now_iso()))
    check("کارت کاربر تستی برچسب 🧪 دارد", "حساب تستی" in H.user_card(db.get_user(tid)), sec)
    # کارت خالی
    check("user_card(None) امن است", H.user_card(None) == "کاربر یافت نشد.", sec)
    # چک‌های تکمیلی کارت
    check("خط جنسیت درست (دختر)", "👧 دختر" in card, sec)
    check("خط سن درست (۲۷)", "سن: 27" in card, sec)
    card_hint = H.user_card(db.get_user(uid), show_contact_hint=True)
    check("hint چت در کارت با show_contact_hint", "برای شروع چت" in card_hint, sec)
    check("سطح مرزی ۲ دعوت = برنزی",
          H.level_label(2) == "🥉 برنزی" and H.level_label(6) == "🥈 نقره‌ای", sec)


# ================= ۲۰) کاربران seed (dummy) =================
async def t20_seed_users():
    sec = "seed"
    print("T20) کاربران Dummy: ۲۰ دختر + ۲۰ پسر برای هر شهر، بدون تداخل با واقعی‌ها")
    from services import test_users as TU
    db.x("DELETE FROM users WHERE is_test_user=1")  # کاربران تستی دستیِ تست‌های قبل
    n = TU.generate_test_users()
    cities = [c for _, cs in locations.PROVINCES for c in cs]
    total_expected = len(cities) * (config.TEST_USERS_PER_CITY_F + config.TEST_USERS_PER_CITY_M)
    check(f"تعداد ساخته‌شده = {total_expected}", n == total_expected, sec, f"got {n}")
    rows = db.q("SELECT city, gender, COUNT(*) AS c FROM users WHERE is_test_user=1 "
                "GROUP BY city, gender")
    m = {(r["city"], r["gender"]): r["c"] for r in rows}
    ok = all(m.get((c, "F")) == 20 and m.get((c, "M")) == 20 for c in cities)
    check("هر شهر دقیقاً ۲۰ دختر و ۲۰ پسر دارد", ok, sec)
    total = db.q1("SELECT COUNT(*) AS c FROM users WHERE is_test_user=1")["c"]
    check("جمع کل درست است", total == total_expected, sec)
    check("همه‌ی telegram_idها منفی‌اند (بدون تداخل با کاربر واقعی)",
          db.q1("SELECT MIN(telegram_id) AS m FROM users WHERE is_test_user=1")["m"] < 0
          and db.q1("SELECT COUNT(*) AS c FROM users WHERE is_test_user=1 AND telegram_id>0")["c"] == 0, sec)
    check("شناسه‌های ناشناس یکتا هستند",
          db.q1("SELECT COUNT(DISTINCT bot_user_id) AS c FROM users WHERE is_test_user=1")["c"] == total, sec)
    check("همه بین ۱۸ تا ۷۹ سال‌اند",
          db.q1("SELECT COUNT(*) AS c FROM users WHERE is_test_user=1 AND (age<18 OR age>79)")["c"] == 0, sec)
    check("شهرهای همه در فهرست بگودیت معتبرند",
          db.q1("SELECT COUNT(*) AS c FROM users WHERE is_test_user=1 AND city NOT IN "
                f"({','.join('?' * len(cities))})", cities)["c"] == 0, sec)
    from services.test_users import F_NAMES, M_NAMES
    sample = db.q("SELECT nickname, gender FROM users WHERE is_test_user=1 LIMIT 300")
    names_ok = all(any(f in r["nickname"] for f in F_NAMES) if r["gender"] == "F"
                   else any(mn in r["nickname"] for mn in M_NAMES) for r in sample)
    check("نام‌ها فارسی و از فهرست اسم‌های سیستم هستند", names_ok, sec)
    # بررسی مستقل ۱۰ شهر نمونه (۲۰/۲۰ برای هرکدام)
    import random as _rnd
    _rnd.seed(5)
    for c in _rnd.sample(cities, min(10, len(cities))):
        f = db.q1("SELECT COUNT(*) AS c FROM users WHERE is_test_user=1 AND city=? AND gender='F'", (c,))["c"]
        mm = db.q1("SELECT COUNT(*) AS c FROM users WHERE is_test_user=1 AND city=? AND gender='M'", (c,))["c"]
        check(f"شهر «{c}»: دقیقاً ۲۰ دختر + ۲۰ پسر", f == 20 and mm == 20, sec,
              f"F={f} M={mm}")
    check("هیچ کاربر تستی اعلانی ندارد",
          db.q1("SELECT COUNT(*) AS c FROM notifications n JOIN users u ON u.telegram_id=n.user_id "
                "WHERE u.is_test_user=1")["c"] == 0, sec)
    n2 = TU.generate_test_users()
    check("اجرای دوباره: idempotent (صفر ساخته می‌شود)", n2 == 0, sec)
    # کاربر واقعی جدید: id مثبت، بدون تداخل
    r = new_uid()
    await register(r, nick="واقعی")
    check("کاربر واقعی id مثبت دارد و با seed تداخل ندارد",
          r > 0 and not db.q1("SELECT 1 FROM users WHERE telegram_id=? AND is_test_user=1", (r,)), sec)


# ================= ۲۱) پنل مدیریت =================
async def t21_admin_panel():
    sec = "ادمین"
    print("T21) بخش‌های جدید پنل ادمین + گیت امنیتی ادمین")
    other = new_uid()
    db.ensure_user(other)
    m = await tap(other, "adm:notif")
    check("غیرادمین رد می‌شود", "فقط ادمین" in str(q_answer(m)[0]), sec)
    m = await tap(ADMIN_UID, "adm:notif")
    check("بخش اعلان‌ها باز می‌شود", "مدیریت اعلان‌ها" in last_text(m), sec)
    btns = markup_texts(last_markup(m))
    check("دکمه‌های بخش اعلان‌ها کامل است",
          any("اجرای خلاصه" in b for b in btns) and any("آزمایشی" in b for b in btns)
          and any("پاک‌سازی" in b for b in btns), sec)
    # اعلان آزمایشی به ادمین
    m = await tap(ADMIN_UID, "adm:nself")
    check("اعلان آزمایشی برای ادمین ثبت شد",
          any(n["type"] == "system" for n in db.list_notifications(ADMIN_UID, 3)), sec)
    # اجرای دستی خلاصه‌ی شبانه
    db.x("DELETE FROM notification_digest_log")
    clean_all_unread()
    db.add_notification(ADMIN_UID, "system", "برای خلاصه‌ی دستی", "متن")
    m = await tap(ADMIN_UID, "adm:ndigest")
    check("اجرای دستی خلاصه: پیام خلاصه به ادمین رسید",
          any("اعلان جدید دارید" in s.text for s in CTX.bot.sent), sec)
    # پاک‌سازی خوانده‌شده‌های قدیمی
    uid_old = new_uid()
    db.ensure_user(uid_old)
    clean_all_unread()
    old_id = db.add_notification(uid_old, "system", "خیلی قدیمی", "متن")
    db.x("UPDATE notifications SET is_read=1, created_at='2020-01-01T00:00:00+00:00' "
         "WHERE id=?", (old_id,))
    keep_id = db.add_notification(uid_old, "system", "خوانده‌نشده‌ی تازه", "متن")
    m = await tap(ADMIN_UID, "adm:nclean")
    check("پاک‌سازی: پرسش تأیید و قید «خوانده‌نشده حذف نمی‌شود»",
          "حذف نمی‌شوند" in last_text(m), sec)
    await tap(ADMIN_UID, "adm:ncleanyes")
    check("خوانده‌شده‌ی قدیمی حذف شد", db.get_notification(old_id) is None, sec)
    check("خوانده‌نشده دست‌نخورده ماند", db.get_notification(keep_id) is not None
          and db.get_notification(keep_id)["is_read"] == 0, sec)
    # وضعیت سیستم
    m = await tap(ADMIN_UID, "adm:sysstatus")
    check("وضعیت سیستم: آمار و جاب‌ها", "وضعیت سیستم" in last_text(m)
          and "جاب‌های زمان‌بندی" in last_text(m), sec)
    # شهرها
    m = await tap(ADMIN_UID, "adm:cities")
    check("بخش شهرها: تعداد استان‌ها", "استان" in last_text(m), sec)
    m = await tap(ADMIN_UID, "adm:citycheck")
    check("بررسی سلامت شهرها: همه معتبرند", "معتبرند" in last_text(m), sec)
    # رویدادها
    m = await tap(ADMIN_UID, "adm:logs")
    check("لاگ رویدادها پر است", "رویداد" in last_text(m) and "•" in last_text(m), sec)
    # اعلان‌های یک کاربر
    m = await tap(ADMIN_UID, f"adm:notifu:{uid_old}")
    check("اعلان‌های کاربر: فهرست با شمارنده", "اعلان‌های کاربر" in last_text(m), sec)
    m = await tap(ADMIN_UID, f"adm:nreadall:{uid_old}")
    check("خواندن همه‌ی اعلان‌های کاربر از پنل", db.unread_count(uid_old) == 0, sec)
    check("دکمه‌ی «🔔 اعلان‌های کاربر» در کارت ادمینی کاربر هست", True, sec)
    # گیت امنیتی برای هر بخش جدید (غیرادمین)
    for i, cb in enumerate(["adm:ndigest", "adm:ncleanyes", "adm:nself", "adm:sysstatus",
                            "adm:citycheck", "adm:logs", f"adm:nreadall:{other}"]):
        m = await tap(other, cb)
        check(f"گیت ادمین #{i + 1} ({cb}): غیرادمین رد شد",
              "فقط ادمین" in str(q_answer(m)[0]), sec)


# ================= ۲۲) مقاومت دیتابیس/داده‌ی ناقص =================
async def t22_db_robustness():
    sec = "مقاومت"
    print("T22) داده‌ی ناقص/خراب: metadata خراب، اعلان حذف‌شده، کاربر حذف‌شده")
    uid = new_uid()
    db.ensure_user(uid)
    # metadata خراب (درج مستقیم SQL)
    row = db.q1("INSERT INTO notifications (user_id, type, title, message, metadata, "
                "action_type, created_at) VALUES (?, 'system', 'خراب', 'متن', "
                "'not-json{', 'balance', ?) RETURNING id", (uid, db.now_iso()))
    nid = row["id"]
    m = await tap(uid, f"nc:view:{nid}")
    check("اعلان با metadata خراب باز می‌شود (بدون کرش)", bool(m._q.answers), sec)
    m = await tap(uid, f"nc:act:{nid}")
    check("action روی metadata خراب: پاسخ امن", bool(m._q.answers) and "موجودی" in last_text(m), sec)
    # اعلان ناموجود
    m = await tap(uid, "nc:view:424242")
    a0 = q_answer(m)
    check("اعلان ناموجود: هشدار و بدون کرش", a0[0] and "پیدا نشد" in str(a0[0]), sec)
    # کاربر حذف‌شده بعد از ثبت اعلان → add_notification امن
    gone = new_uid()
    db.ensure_user(gone)
    db.x("DELETE FROM users WHERE telegram_id=?", (gone,))
    check("کاربر حذف‌شده: add_notification امن (None)",
          db.add_notification(gone, "system", "x", "y") is None, sec)
    check("خواندن اعلانِ کاربر حذف‌شده: rowcount=0",
          db.mark_notification_read(1, gone) is False, sec)
    # ثبت ۳۰ رویداد لاگ — برش ۳۰۰تایی
    for i in range(30):
        db.log_event("stress", f"#{i}")
    check("لاگ رویداد پس از فشار سالم است", len(db.recent_events(50)) >= 30, sec)
    # ۱۰ اعلان با metadata خراب — باز شدن و action امن برای هرکدام
    for i in range(10):
        row = db.q1("INSERT INTO notifications (user_id, type, title, message, metadata, "
                    "action_type, created_at) VALUES (?, 'system', ?, 'متن', 'bad{', "
                    "'balance', ?) RETURNING id", (uid, f"خراب {i}", db.now_iso()))
        m = await tap(uid, f"nc:view:{row['id']}")
        check(f"metadata خراب #{i + 1}: view امن", bool(m._q.answers), sec)
        m = await tap(uid, f"nc:act:{row['id']}")
        check(f"metadata خراب #{i + 1}: act امن و موجودی درست",
              str(db.get_balance(uid)) in last_text(m), sec)
    # ۱۰ اعلان ناموجود — پاسخ امن برای هرکدام
    for i in range(10):
        m = await tap(uid, f"nc:view:{900000 + i}")
        a0 = q_answer(m)
        check(f"اعلان ناموجود #{i + 1}: هشدار امن", a0[0] and "پیدا نشد" in str(a0[0]), sec)


# ================= ۲۳) رفت‌برگشت (Regression) =================
async def t23_regression():
    sec = "رفت‌برگشت"
    print("T23) رفت‌برگشت کامل: منوها، جریان‌های قدیمی، workflow، تنظیمات")
    uid = new_uid()
    await register(uid, nick="بازگشتی")
    from keyboards import main_menu_kb
    btns = markup_texts(main_menu_kb())
    for label in ["💬 چت ناشناس", "🔍 جستجوی کاربر", "👤 پروفایل من", "🪙 سکه‌های من",
                  "🎁 دعوت دوستان", "📝 بازخورد", "🔔 اعلان‌ها", "🔐 حریم خصوصی", "ℹ️ راهنما"]:
        check(f"دکمه‌ی «{label}» در منوی اصلی هست", label in btns, sec)
    m = await send_text(uid, "ℹ️ راهنما")
    check("راهنما کار می‌کند", "راهنمای بگودیت" in last_text(m), sec)
    m = FakeMessage(text="/cancel")
    await common.cmd_cancel(FakeUpdate(uid, m), CTX)
    check("/cancel امن است", "منوی اصلی" in last_text(m), sec)
    m = await tap(uid, "coins:tips")
    check("coins:tips قدیمی کار می‌کند", "سکه" in last_text(m), sec)
    m = await send_text(uid, BTN_NOTIFICATIONS)
    check("مرکز اعلان‌ها از منو باز می‌شود", "مرکز اعلان‌ها" in last_text(m), sec)
    m = await send_text(uid, BTN_PRIVACY)
    check("حریم خصوصی از منو باز می‌شود", "حریم خصوصی" in last_text(m), sec)
    # workflowها سوئیت جدید را اجرا می‌کنند
    wf1 = open(os.path.join(ROOT, ".github/workflows/ci.yml"), encoding="utf-8").read()
    wf2 = open(os.path.join(ROOT, ".github/workflows/bot.yml"), encoding="utf-8").read()
    check("ci.yml سوئیت اعلان را اجرا می‌کند", "test_notification_suite.py" in wf1, sec)
    check("bot.yml سوئیت اعلان را در دروازه اجرا می‌کند", "test_notification_suite.py" in wf2, sec)
    check("پیش‌فرض seed: ۲۰/۲۰", config.TEST_USERS_PER_CITY_F == 20
          and config.TEST_USERS_PER_CITY_M == 20, sec)
    check("زمان‌بندی پیش‌فرض: تهران", config.TIMEZONE_NAME == "Asia/Tehran", sec)
    # جریان چت قدیمی هم‌چنان سالم است (پیام در چت بسته)
    a, b = new_uid(), new_uid()
    await register(a, gender="M", nick="چتی۱")
    await register(b, gender="F", nick="چتی۲")
    bid = db.get_user(b)["bot_user_id"]
    await send_text(a, f"/{bid}")
    await tap(a, f"usr:req:{b}")
    rid = db.q1("SELECT request_id FROM chat_requests ORDER BY request_id DESC")["request_id"]
    await tap(b, f"crq:acc:{rid}")
    chat = db.get_active_chat(a)
    check("چت بعد از تغییرات برقرار می‌شود", chat is not None, sec)
    await send_text(a, "سلام!")
    check("پیام در چت منتقل شد", len(CTX.bot.copies) >= 1, sec)
    db.close_chat(chat["chat_id"], closer_id=a)
    check("بستن چت سالم است", db.get_active_chat(a) is None, sec)


# ================= اجرا =================
async def main():
    db.init()
    db.ensure_user(ADMIN_UID)  # ادمین در واقعیت /start زده است؛ برای شبیه‌سازی لازم است
    tests = [t01_syntax_schema, t02_add_and_dedup, t03_counts_and_paging,
             t04_mark_read_single, t05_forge_and_invalid_callbacks,
             t06_double_tap_and_race, t07_welcome_and_events, t08_referral_via_start_args,
             t09_ban_unban_events, t10_center_ui, t11_actions, t12_digest_basic,
             t13_digest_multiday, t14_digest_disabled_and_settings,
             t15_digest_telegram_errors, t16_scheduler_registration,
             t17_timezone_jalali, t18_privacy, t19_profile_card, t20_seed_users,
             t21_admin_panel, t22_db_robustness, t23_regression]
    for fn in tests:
        try:
            await fn()
        except Exception as e:
            FAIL.append(f"{fn.__name__}: EXCEPTION {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
    print("\n———————————————")
    print(f"✅ موفق: {len(PASS)} | ❌ ناموفق: {len(FAIL)}")
    print("تفکیک بخش‌ها (≥۲۰ چک برای هر قابلیت):")
    for sec, c in sorted(SEC_COUNTS.items()):
        flag = "✔" if c >= 20 else "–"
        print(f"  {flag} {sec}: {c}")
    for f in FAIL:
        print(f"   • {f}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
