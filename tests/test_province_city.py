"""تست‌های سناریویی «انتخاب استان و شهر» بگودیت — اجرا: python3 tests/test_province_city.py

این تست‌ها مسیر واقعی پردازش پیام (common.route_text / common.cb_router) و
هندلرهای واقعی ثبت‌نام را با آبجکت‌های شبیه‌سازی‌شده تلگرام اجرا می‌کنند و
دیتابیس موقت (جدای از دیتابیس اصلی) استفاده می‌کنند.
"""
import asyncio
import os
import sys
import tempfile

# دیتابیس موقت — باید «قبل از» ایمپورت config ست شود
_TMPDIR = tempfile.mkdtemp(prefix="bagoodit-test-")
os.environ["DB_PATH"] = os.path.join(_TMPDIR, "test.db")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
import database as db  # noqa: E402
import locations  # noqa: E402
from handlers import common  # noqa: E402
from keyboards import BTN_PROV_BACK  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append(f"{name} {detail}")
        print(f"  ❌ {name} {detail}")


def reply_markup_texts(kb) -> list:
    if kb is None:
        return []
    grid = getattr(kb, "keyboard", None) or getattr(kb, "inline_keyboard", None)
    return [[b.text for b in row] for row in grid]


def flat_texts(kb) -> list:
    return [t for row in reply_markup_texts(kb) for t in row]


# ---------------- فیک‌های تلگرام ----------------
class Sent:
    def __init__(self, text="", markup=None, photo=None):
        self.text, self.markup, self.photo = text, markup, photo


class FakeMessage:
    def __init__(self, text=None, photo=None):
        self.text = text
        self.photo = photo
        self.outbox = []

    async def reply_text(self, text, parse_mode=None, reply_markup=None, **kw):
        self.outbox.append(Sent(text, reply_markup))
        return self

    async def reply_photo(self, photo=None, caption=None, parse_mode=None,
                          reply_markup=None, **kw):
        self.outbox.append(Sent(caption, reply_markup, photo=photo))
        return self

    async def edit_reply_markup(self, reply_markup=None):
        self.outbox.append(Sent("", reply_markup))
        return self

    @property
    def last(self):
        return self.outbox[-1] if self.outbox else None


class FakeBot:
    def __init__(self):
        self.sent = []
        self.photos = []

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None, **kw):
        self.sent.append(Sent(text, reply_markup))

    async def send_photo(self, chat_id, photo, caption=None, parse_mode=None,
                         reply_markup=None, **kw):
        self.sent.append(Sent(caption, reply_markup, photo=photo))
        self.photos.append(Sent(caption, reply_markup, photo=photo))


class FakeCallbackQuery:
    def __init__(self, data: str, uid: int, message: FakeMessage):
        self.data = data
        self.from_user = type("U", (), {"id": uid})()
        self.message = message
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class FakeUpdate:
    def __init__(self, uid: int, message: FakeMessage = None, cbq: FakeCallbackQuery = None):
        self.message = message
        self.callback_query = cbq
        self.effective_user = type("U", (), {"id": uid})()
        self.effective_message = message or (cbq.message if cbq else None)


class FakeContext:
    def __init__(self):
        self.bot = FakeBot()
        self.args = []


CTX = FakeContext()


# ---------------- کمک‌سازهای جریان ----------------
async def send_text(uid: int, text: str) -> FakeMessage:
    m = FakeMessage(text=text)
    await common.route_text(FakeUpdate(uid, m), CTX)
    return m


async def tap(uid: int, data: str) -> FakeMessage:
    m = FakeMessage()
    await common.cb_router(FakeUpdate(uid, cbq=FakeCallbackQuery(data, uid, m)), CTX)
    return m


def user_row(uid: int):
    return db.get_user(uid)


_uid_seq = 700000


def new_uid() -> int:
    global _uid_seq
    _uid_seq += 1
    return _uid_seq


async def _register(uid: int, prov: str, city: str, nick: str):
    from fakes import fake_photo
    await drive_to_province(uid)
    await send_text(uid, prov)
    await send_text(uid, city)
    await send_text(uid, nick)
    # عکس اجباری (قانون جدید) — بدون عکس ثبت‌نام کامل نمی‌شود
    await common.route_media(
        FakeUpdate(uid, FakeMessage(photo=[fake_photo(f"ava-{uid}")])), CTX)


async def drive_to_province(uid: int, gender="F", age="25"):
    """/start → جنسیت → سن؛ خروجی: پیام «انتخاب استان»."""
    await send_text(uid, "/start")
    await tap(uid, "reg:gender:F" if gender == "F" else "reg:gender:M")
    m = await send_text(uid, age)
    return m


# ================= سناریوها =================
async def t01_full_happy_path():
    print("T1) ثبت‌نام کامل تا شهر")
    uid = new_uid()
    m = await drive_to_province(uid)
    kb = m.last.markup
    check("پس از سن، کیبورد Reply استان نمایش داده شود",
          kb is not None and "ReplyKeyboardMarkup" in type(kb).__name__)
    check("۳۱ استان روی کیبورد باشد", len(flat_texts(kb)) == 31)
    m2 = await send_text(uid, "تهران")
    city_btns = flat_texts(m2.last.markup)
    check("پس از انتخاب استان، کیبورد شهرهای همان استان باشد",
          "ری" in city_btns and "ورامین" in city_btns and BTN_PROV_BACK in city_btns)
    check("شهرِ استان دیگر روی کیبورد نباشد", "شیراز" not in city_btns)
    m3 = await send_text(uid, "ری")
    check("پس از انتخاب شهر، مرحله نام مستعار شروع شود", "اسم مستعار" in (m3.last.text or ""))
    row = user_row(uid)
    check("استان در دیتابیس ذخیره شود", row["province"] == "تهران", f"got={row['province']}")
    check("شهر در دیتابیس ذخیره شود", row["city"] == "ری", f"got={row['city']}")
    # ادامه تا پایان ثبت‌نام: نام مستعار + رد کردن عکس
    await send_text(uid, "علی")
    await send_text(uid, "⏭ رد کردن عکس")
    row = user_row(uid)
    check("ثبت‌نام کامل شود", db.is_registered(row), f"state={row['state']}")


async def t02_all_31_provinces():
    print("T2) انتخاب هر ۳۱ استان + چند شهر از هر استان")
    for pname, cities in locations.PROVINCES:
        uid = new_uid()
        m = await drive_to_province(uid)
        sent = flat_texts(m.last.markup)
        if sent != locations.display_provinces():
            check(f"کیبورد استان‌ها ({pname})", False, "ترتیب/تعداد غلط")
            return
        m2 = await send_text(uid, pname)
        kb = m2.last.markup
        btns = flat_texts(kb)
        want = cities + [BTN_PROV_BACK]
        if btns != want:
            check(f"شهرهای {pname}", False, f"got={btns[:6]}…")
            return
        # چند شهر از هر استان: اولی، وسطی، آخری
        picks = {cities[0], cities[len(cities) // 2], cities[-1]}
        for c in picks:
            u2 = new_uid()
            await drive_to_province(u2)
            await send_text(u2, pname)
            await send_text(u2, c)
            row = user_row(u2)
            if not (row["province"] == pname and row["city"] == c):
                check(f"ذخیره {pname}/{c}", False, f"got={row['province']}/{row['city']}")
                return
        check(f"استان «{pname}» ({len(cities)} شهر)", True)


async def t03_invalid_province():
    print("T3) متن نامعتبر به‌جای استان")
    uid = new_uid()
    await drive_to_province(uid)
    m = await send_text(uid, "آلمان")
    row = user_row(uid)
    check("ثبت‌نام جلو نرود", row["state"] == config.ST_REG_PROVINCE)
    check("پیام راهنما + کیبورد استان دوباره نمایش داده شود",
          "استان نامعتبر" in (m.last.text or "") and m.last.markup is not None)
    m2 = await send_text(uid, "استانم رو نمیگم")
    check("متن آزاد هم رد شود", user_row(uid)["state"] == config.ST_REG_PROVINCE
          and "استان نامعتبر" in (m2.last.text or ""))


async def t04_invalid_city():
    print("T4) متن نامعتبر / شهرِ استان دیگر")
    uid = new_uid()
    await drive_to_province(uid)
    await send_text(uid, "تهران")
    m = await send_text(uid, "پاریس")
    check("شهر نامعتبر رد شود", user_row(uid)["state"] == config.ST_REG_CITY
          and "شهر نامعتبر" in (m.last.text or ""))
    m2 = await send_text(uid, "کاشان")  # شهر اصفهان — نه شهر قم و نه نام استان
    check("شهرِ استان دیگر رد شود", user_row(uid)["state"] == config.ST_REG_CITY
          and "شهر نامعتبر" in (m2.last.text or ""))
    row = user_row(uid)
    check("چیزی در دیتابیس نوشته نشود", row["city"] is None)
    # تعویض استان از مرحله شهر (نام استان معتبر) باید کار کند — پوشش ضربه سریع
    m3 = await send_text(uid, "اصفهان")
    check("نام استان معتبر در مرحله شهر → تعویض استان",
          user_row(uid)["state"] == config.ST_REG_CITY
          and "کاشان" in flat_texts(m3.last.markup))
    m3b = await send_text(uid, "قم")   # «قم» شهر اصفهان نیست → تعویض استان
    check("تعویض به استان قم انجام شود", "استان «قم»" in (m3b.last.text or ""))
    m4 = await send_text(uid, "قم")    # حالا «قم» شهرِ استان جاری است → انتخاب شهر
    check("شهرِ هم‌نام استان، شهر حساب شود", user_row(uid)["city"] == "قم"
          and "اسم مستعار" in (m4.last.text or ""))


async def t05_rapid_taps():
    print("T5) ضربه سریع چندباره روی دکمه استان")
    uid = new_uid()
    await drive_to_province(uid)
    await send_text(uid, "تهران")
    await send_text(uid, "البرز")   # بدون مکث، استان عوض می‌شود
    await send_text(uid, "فارس")
    row = user_row(uid)
    check("آخرین انتخاب معتبر بماند", row["state"] == config.ST_REG_CITY)
    m = await send_text(uid, "شیراز")
    check("شهرِ آخرین استان پذیرفته شود", "اسم مستعار" in (m.last.text or ""))
    row = user_row(uid)
    check("استان/شهر نهایی درست باشد", row["province"] == "فارس" and row["city"] == "شیراز",
          f"got={row['province']}/{row['city']}")


async def t06_start_during_province():
    print("T6) ارسال /start در مرحله انتخاب استان")
    uid = new_uid()
    await drive_to_province(uid)
    # /start مثل تلگرام از CommandHandler می‌گذرد
    await common.cmd_start(FakeUpdate(uid, FakeMessage(text="/start")), CTX)
    row = user_row(uid)
    check("ثبت‌نام از اول (جنسیت) شروع شود", row["state"] == config.ST_REG_GENDER)
    # و جریان از نو کامل شود
    await tap(uid, "reg:gender:M")
    await send_text(uid, "30")
    await send_text(uid, "یزد")
    await send_text(uid, "میبد")
    await send_text(uid, "امید")
    row = user_row(uid)
    check("جریان بعد از ری‌استارت کامل شود", row["province"] == "یزد" and row["city"] == "میبد")


async def t07_restart_lost_context():
    print("T7) خروج/ورود مجدد و کانتکست گم‌شده")
    uid = new_uid()
    await drive_to_province(uid)
    await send_text(uid, "مازندران")
    # شبیه‌سازی گم‌شدن کانتکست (مثلاً خرابی وسط کار)
    db.set_state(uid, config.ST_REG_CITY, {})
    m = await send_text(uid, "ساری")
    check("با کانتکست خالی، دوباره استان پرسیده شود",
          user_row(uid)["state"] == config.ST_REG_PROVINCE
          and "استان" in (m.last.text or ""))
    await send_text(uid, "مازندران")
    await send_text(uid, "ساری")
    row = user_row(uid)
    check("جریان بعد از بازیابی کامل شود",
          row["province"] == "مازندران" and row["city"] == "ساری",
          f"got={row['province']}/{row['city']}")


async def t08_profile_edit_change_province():
    print("T8) تغییر استان در پروفایل → پاک‌شدن شهر قبلی")
    uid = new_uid()
    await _register(uid, "تهران", "ری", "نیلا")
    check("کاربر اولیه ثبت شده", db.is_registered(user_row(uid)))
    m = await tap(uid, "pf:edit:city")
    check("ویرایش شهر → کیبورد استان نمایش داده شود",
          user_row(uid)["state"] == config.ST_REG_PROVINCE
          and len(flat_texts(m.last.markup)) == 31)
    m2 = await send_text(uid, "اصفهان")
    row = user_row(uid)
    check("با تغییر استان، شهر قبلی پاک شود",
          row["province"] == "اصفهان" and row["city"] is None,
          f"got={row['province']}/{row['city']}")
    check("کاربر موقتاً ثبت‌نشده محسوب شود (بدون شهر)", not db.is_registered(row))
    check("کیبورد شهرهای استان جدید نمایش داده شود", "کاشان" in flat_texts(m2.last.markup))
    m3 = await send_text(uid, "کاشان")
    row = user_row(uid)
    check("شهر جدید ذخیره و پروفایل نمایش داده شود",
          row["province"] == "اصفهان" and row["city"] == "کاشان"
          and row["state"] == config.ST_MAIN)
    last_card = (m3.last.text if m3.last else "") or ""
    caps = [p.text or "" for p in CTX.bot.photos]
    check("کارت پروفایل پس از ویرایش ارسال شود",
          "نیلا" in last_card or any("نیلا" in c for c in caps))
    _ = caps  # نگه‌داشتن ارجاع برای خوانایی


async def t09_profile_edit_same_province():
    print("T9) ویرایش شهر با همان استان قبلی")
    uid = new_uid()
    await _register(uid, "گیلان", "رشت", "آرمان دو")
    await tap(uid, "pf:edit:city")
    await send_text(uid, "گیلان")
    row = user_row(uid)
    check("با انتخاب همان استان، شهر قبلی پاک نشود", row["city"] == "رشت")
    await send_text(uid, "لاهیجان")
    row = user_row(uid)
    check("شهر جدید ذخیره شود", row["province"] == "گیلان" and row["city"] == "لاهیجان")


async def t10_multi_user():
    print("T10) چند کاربر همزمان — بدون تداخل")
    a, b = new_uid(), new_uid()
    await drive_to_province(a)
    await drive_to_province(b)
    await send_text(b, "فارس")
    await send_text(a, "تهران")
    await send_text(b, "کازرون")
    await send_text(a, "ورامین")
    ra, rb = user_row(a), user_row(b)
    check("کاربر اول سالم", ra["province"] == "تهران" and ra["city"] == "ورامین",
          f"got={ra['province']}/{ra['city']}")
    check("کاربر دوم سالم", rb["province"] == "فارس" and rb["city"] == "کازرون",
          f"got={rb['province']}/{rb['city']}")


async def t11_legacy_inline_buttons():
    print("T11) دکمه‌های قدیمی اینلاین (پیام‌های قبل از آپدیت)")
    uid = new_uid()
    await drive_to_province(uid)
    m = await tap(uid, "reg:prov:0")  # تهران با ایندکس قدیمی
    check("دکمه قدیمی استان کار کند", user_row(uid)["state"] == config.ST_REG_CITY
          and "ری" in flat_texts(m.last.markup))
    await tap(uid, "reg:city:0:1")  # اسلامشهر با ایندکس قدیمی
    row = user_row(uid)
    check("دکمه قدیمی شهر کار کند",
          row["province"] == "تهران" and row["city"] == "اسلامشهر",
          f"got={row['province']}/{row['city']}")
    # دکمه قدیمی وقتی کاربر در آن مرحله نیست → بی‌اثر
    uid2 = new_uid()
    await _register(uid2, "قم", "قم", "مهمان")
    await tap(uid2, "reg:prov:3")
    row2 = user_row(uid2)
    check("دکمه قدیمی خارج از مرحله، وضعیت را خراب نکند",
          row2["state"] == config.ST_MAIN and row2["province"] == "قم")
    # دکمه صفحه‌بندی قدیمی → فقط توست، بدون کرش
    uid3 = new_uid()
    await drive_to_province(uid3)
    await tap(uid3, "reg:page:1")
    check("دکمه صفحه‌بندی قدیمی بدون خطا پاسخ داده شود", True)


async def t12_keyboard_shapes():
    print("T12) ساختار کیبوردها + یکسان‌سازی نام‌ها")
    from keyboards import cities_reply_kb, provinces_reply_kb
    kb = provinces_reply_kb()
    rows = reply_markup_texts(kb)
    check("۳ دکمه در هر ردیف استان (به‌جز ردیف آخر)",
          all(len(r) == 3 for r in rows[:-1]) and len(rows[-1]) == 1)
    check("۳۱ استان در کیبورد", len(flat_texts(kb)) == 31)
    check("ترتیب الفبایی مطابق فهرست رسمی", flat_texts(kb) == list(locations.DISPLAY_ORDER))
    check("DISPLAY_ORDER دقیقاً همان ۳۱ استان دیتاست باشد",
          sorted(locations.DISPLAY_ORDER) == sorted(p for p, _ in locations.PROVINCES))
    for pname, cities in locations.PROVINCES:
        ckb = cities_reply_kb(pname)
        got = flat_texts(ckb)
        if got != cities + [BTN_PROV_BACK]:
            check(f"کیبورد شهر {pname}", False)
            return
    check("کیبورد شهرها برای هر ۳۱ استان درست است", True)
    # یکسان‌سازی: حروف عربی، نیم‌فاصله، فاصله اضافه
    check("«كهگیلویه...» با ک عربی هم بپذیرد",
          locations.province_by_name("كهگیلویه و بویراحمد") == "کهگیلویه و بویراحمد")
    check("«تهران   » با فاصله اضافه هم بپذیرد",
          locations.province_by_name("  تهران   ") == "تهران")
    check("«رباط کریم» بدون نیم‌فاصله هم بپذیرد",
          locations.city_in_province("تهران", "رباط کریم") == "رباط‌کریم")
    check("شهرِ استان دیگر در همان استان قبول نشود",
          locations.city_in_province("قم", "کاشان") is None)


async def t13_fw_wizard_fixed():
    print("T13) ویزارد جست‌وجوی پیشرفته (fw) که با همان باگ می‌سوخت")
    from keyboards import cities_kb
    kb = cities_kb(0, 0)  # قبلاً همین‌جا TypeError می‌داد
    check("cities_kb بدون خطا ساخته شود", kb is not None)
    btns = flat_texts(kb)
    check("صفحه اول شهرهای تهران کامل باشد", btns == [
        "تهران", "اسلامشهر", "ری", "ورامین", "شهریار", "ملارد",
        "پاکدشت", "پیشوا", "بهارستان", "پردیس", "قدس", "رباط‌کریم",
        "🏙 تغییر استان"])
    for idx in range(len(locations.PROVINCES)):
        cities_kb(idx, 0)
    check("cities_kb برای هر ۳۱ استان بدون خطا بسازد", True)
    # کل مسیر ویزارد با هندلر واقعی
    uid = new_uid()
    await _register(uid, "قم", "قم", "ویزاردی")
    await send_text(uid, "💬 چت ناشناس")
    await send_text(uid, "🟣 جستجوی پیشرفته")
    await send_text(uid, "20")
    await send_text(uid, "40")
    await send_text(uid, "25")  # مرحله max → قبول؛ حالا مرحله city با کیبورد inline استان
    await tap(uid, "fw:prov:3")  # فارس
    await tap(uid, "fw:city:3:0")  # شیراز
    row = user_row(uid)
    check("ویزارد تا صف انتظار کامل شود", row["state"] == config.ST_SEARCHING,
          f"got={row['state']}")
    ctx = db.get_ctx(row)
    check("معیار جست‌وجو درست ذخیره شود",
          ctx.get("search", {}).get("city") == "شیراز"
          and ctx.get("search", {}).get("province") == "فارس")
    await common.cmd_cancel(FakeUpdate(uid, FakeMessage(text="/cancel")), CTX)  # پاکسازی صف


async def t14_existing_users_safe():
    print("T14) کاربران قبلی آسیب نبینند")
    uid = new_uid()
    db.ensure_user(uid)  # کاربر قدیمی از قبل وجود داشته
    db.update_user(uid, nickname="قدیمی", gender="M", age=33,
                   province="خراسان رضوی", city="مشهد")
    before = dict(user_row(uid))
    await _register(new_uid(), "تهران", "ری", "تازه")
    after = dict(user_row(uid))
    check("ردیف کاربر قدیمی دست‌نخورده بماند",
          before["province"] == after["province"] and before["city"] == after["city"]
          and before["nickname"] == after["nickname"])
    cols = [r["name"] for r in db.q("PRAGMA table_info(users)")]
    check("اسکیمای دیتابیس تغییر نکرده باشد",
          "province" in cols and "city" in cols and len(cols) == 16)


async def t15_matching_gate():
    print("T15) کاربرِ وسط تغییر استان، در تطبیق شرکت نکند")
    from services.matching import _profile_ok
    uid = new_uid()
    await _register(uid, "تهران", "ری", "گیت")
    check("کاربر کامل، پروفایلش معتبر است", _profile_ok(user_row(uid)))
    await tap(uid, "pf:edit:city")
    await send_text(uid, "یزد")
    check("بعد از تغییر استان (قبل از انتخاب شهر)، پروفایل نامعتبر شود",
          not _profile_ok(user_row(uid)))


# ---------------- اجرا ----------------
async def main():
    db.init()
    for fn in (t01_full_happy_path, t02_all_31_provinces, t03_invalid_province,
               t04_invalid_city, t05_rapid_taps, t06_start_during_province,
               t07_restart_lost_context, t08_profile_edit_change_province,
               t09_profile_edit_same_province, t10_multi_user,
               t11_legacy_inline_buttons, t12_keyboard_shapes, t13_fw_wizard_fixed,
               t14_existing_users_safe, t15_matching_gate):
        try:
            await fn()
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
