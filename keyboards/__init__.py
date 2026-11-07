"""همه کیبوردها و متن دکمه‌ها — رنگ دکمه‌ها فقط با ایموجی (API تلگرام رنگ ندارد)."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove

import config
from utils.helpers import chunk

# ---------- دکمه‌های متن ----------
BTN_ANON_CHAT = "💬 چت ناشناس"
BTN_SEARCH_USER = "🔍 جستجوی کاربر"
BTN_PROFILE = "👤 پروفایل من"
BTN_COINS = "🪙 سکه‌های من"
BTN_REFERRAL = "🎁 دعوت دوستان"
BTN_FEEDBACK = "📝 بازخورد"
BTN_NOTIFICATIONS = "🔔 اعلان‌ها"
BTN_PRIVACY = "🔐 حریم خصوصی"
BTN_HELP = "ℹ️ راهنما"

BTN_MATCH_RANDOM = "🟢 چت تصادفی"
BTN_MATCH_GIRL = "🔵 جستجوی دختر"
BTN_MATCH_BOY = "🔵 جستجوی پسر"
BTN_MATCH_NEARBY = "🔴 افراد نزدیک"
BTN_MATCH_FILTER = "🟣 جستجوی پیشرفته"
BTN_BACK = "⬅️ بازگشت"
BTN_CANCEL_SEARCH = "❌ لغو جستجو"

BTN_CHAT_PROFILE = "🟢 پروفایل طرف مقابل"
BTN_CHAT_REPORT = "⚠️ گزارش کاربر"
BTN_CHAT_END = "🔴 پایان چت"

BTN_SKIP_PHOTO = "⏭ رد کردن عکس"
BTN_FEMALE = "👧 دختر"
BTN_MALE = "👦 پسر"
BTN_PROV_BACK = "⬅️ انتخاب مجدد استان"

remove_kb = ReplyKeyboardRemove()


# ---------- کیبوردهای پاسخ (Reply) ----------
def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[BTN_ANON_CHAT, BTN_SEARCH_USER],
         [BTN_PROFILE, BTN_COINS],
         [BTN_REFERRAL, BTN_FEEDBACK],
         [BTN_NOTIFICATIONS, BTN_PRIVACY],
         [BTN_HELP]],
        resize_keyboard=True, input_field_placeholder="گزینه‌ای را انتخاب کن…")


def match_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[BTN_MATCH_RANDOM],
         [BTN_MATCH_GIRL, BTN_MATCH_BOY],
         [BTN_MATCH_NEARBY],
         [BTN_MATCH_FILTER],
         [BTN_BACK]],
        resize_keyboard=True, input_field_placeholder="نوع جستجو را انتخاب کن…")


def searching_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[BTN_CANCEL_SEARCH]], resize_keyboard=True)


def chat_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[BTN_CHAT_PROFILE, BTN_CHAT_REPORT],
         [BTN_CHAT_END]],
        resize_keyboard=True, input_field_placeholder="پیامت را بنویس…")


def age_kb() -> ReplyKeyboardMarkup:
    ages = [str(a) for a in range(config.AGE_MIN, config.AGE_MAX + 1)]
    return ReplyKeyboardMarkup(chunk(ages, 8), resize_keyboard=True,
                               one_time_keyboard=True,
                               input_field_placeholder="سن خود را انتخاب کن…")


def skip_photo_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[BTN_SKIP_PHOTO]], resize_keyboard=True)


def provinces_reply_kb() -> ReplyKeyboardMarkup:
    """۳۱ استان به‌صورت کیبورد Reply واقعی — ۳ دکمه در هر ردیف."""
    import locations
    rows = chunk(locations.display_provinces(), 3)
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True,
                               input_field_placeholder="استان را انتخاب کن…")


def cities_reply_kb(prov: str) -> ReplyKeyboardMarkup:
    """شهرهای همان استان با کیبورد Reply — ۳ دکمه در هر ردیف + دکمه بازگشت."""
    import locations
    rows = chunk(locations.cities_of(prov), 3)
    rows.append([BTN_PROV_BACK])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True,
                               input_field_placeholder="شهر را انتخاب کن…")


# ---------- کیبوردهای درون‌خطی (Inline) ----------
def gender_kb(prefix="reg") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(BTN_FEMALE, callback_data=f"{prefix}:gender:F"),
        InlineKeyboardButton(BTN_MALE, callback_data=f"{prefix}:gender:M"),
    ]])


def provinces_kb(page=0, prefix="reg") -> InlineKeyboardMarkup:
    provs = [(i, name) for i, (name, _) in enumerate(config_provinces())]
    pages = chunk(provs, config.PROV_PAGE_SIZE)
    page = max(0, min(page, len(pages) - 1))
    rows = [[InlineKeyboardButton(name, callback_data=f"{prefix}:prov:{i}")]
            for i, name in pages[page]]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("➡️ قبلی", callback_data=f"{prefix}:page:{page-1}"))
    nav.append(InlineKeyboardButton(f"📄 {page+1}/{len(pages)}", callback_data=f"{prefix}:noop"))
    if page < len(pages) - 1:
        nav.append(InlineKeyboardButton("⬅️ بعدی", callback_data=f"{prefix}:page:{page+1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(rows)


def cities_kb(pidx: int, page=0, prefix="reg") -> InlineKeyboardMarkup:
    import locations
    p = locations.province_by_index(pidx)
    if not p:
        return provinces_kb(0, prefix)
    cities = list(enumerate(p[1]))
    pages = chunk(cities, config.CITY_PAGE_SIZE)
    page = max(0, min(page, len(pages) - 1))
    rows = []
    # هر صفحه یک فهرست تخت از (ایندکس، شهر) است؛ آن را به ردیف‌های ۴تایی می‌شکنیم.
    for grp in chunk(pages[page], 4):
        rows.append([InlineKeyboardButton(city, callback_data=f"{prefix}:city:{pidx}:{i}")
                     for i, city in grp])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("➡️ قبلی", callback_data=f"{prefix}:cpage:{pidx}:{page-1}"))
    if len(pages) > 1:
        nav.append(InlineKeyboardButton(f"📄 {page+1}/{len(pages)}", callback_data=f"{prefix}:noop"))
    if page < len(pages) - 1:
        nav.append(InlineKeyboardButton("⬅️ بعدی", callback_data=f"{prefix}:cpage:{pidx}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🏙 تغییر استان", callback_data=f"{prefix}:back")])
    return InlineKeyboardMarkup(rows)


def config_provinces():
    import locations
    return locations.PROVINCES


def profile_kb(has_avatar: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("✏️ تغییر نام", callback_data="pf:edit:nickname"),
         InlineKeyboardButton("🎂 تغییر سن", callback_data="pf:edit:age")],
        [InlineKeyboardButton("🚻 تغییر جنسیت", callback_data="pf:edit:gender"),
         InlineKeyboardButton("🏙 تغییر شهر", callback_data="pf:edit:city")],
        [InlineKeyboardButton("🖼 تغییر عکس", callback_data="pf:edit:photo"),
         InlineKeyboardButton("🗑 حذف عکس", callback_data="pf:delphoto") if has_avatar
         else InlineKeyboardButton("👤 پروفایل", callback_data="pf:noop")],
        [InlineKeyboardButton("⬅️ بازگشت به منو", callback_data="pf:back")],
    ]
    return InlineKeyboardMarkup(rows)


def coins_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🎁 چطور سکه بگیرم؟", callback_data="coins:tips")]])


def report_reasons_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(r, callback_data=f"rpt:{i}")]
            for i, r in enumerate(config.REPORT_REASONS)]
    rows.append([InlineKeyboardButton("انصراف", callback_data="rpt:cancel")])
    return InlineKeyboardMarkup(rows)


def request_kb(rid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ قبول", callback_data=f"crq:acc:{rid}"),
        InlineKeyboardButton("❌ رد", callback_data=f"crq:dec:{rid}"),
    ]])


def confirm_kb(yes_cb: str, no_cb: str, yes="✅ بله", no="❌ نه") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(yes, callback_data=yes_cb),
        InlineKeyboardButton(no, callback_data=no_cb),
    ]])
