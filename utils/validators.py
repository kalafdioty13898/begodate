"""اعتبارسنجی ورودی‌ها — نام مستعار فقط فارسی + تشخیص واقعی یونیکد.
قواعد نام:
• فقط حروف فارسی (حروف عربی مشابه به فارسی استاندارد تبدیل می‌شوند)
• فاصله بین کلمات مجاز، نیم‌فاصله (U+200C) مجاز
• حروف انگلیسی/لاتین، اعداد (فارسی/عربی/انگلیسی) و نمادها غیرمجاز
• خالی/فقط فاصله غیرمجاز؛ طول بین NICK_MIN و NICK_MAX
• HTML/Markdown هرگز باعث خطا نمی‌شود (همه‌چیز متن ساده در نظر گرفته می‌شود)
"""
import re
import unicodedata

import config

# پیام خطای رسمی (طبق مشخصات پروژه)
NAME_FA_ERROR = "❌ نام کاربری باید فقط فارسی باشد. لطفاً نام خود را با حروف فارسی وارد کنید."

# نگاشت حروف عربی به معادل فارسی
_AR_TO_FA = str.maketrans({
    "ي": "ی", "ك": "ک", "ﻯ": "ی", "ﻰ": "ی", "ى": "ی",
    "أ": "ا", "إ": "ا", "ٱ": "ا", "ؤ": "و", "ئ": "ی",
    "ۀ": "ه", "ة": "ه", "ﺁ": "آ",
})

_ZWNJ = "\u200c"
# کاراکترهای صفر-عرض دیگر (به‌جز نیم‌فاصله) حذف می‌شوند
_ZERO_WIDTH = re.compile(r"[\u200b\u200e\u200f\u202a-\u202e\u2060\ufeff]")

# بازه‌های یونیکد حروف عربی/فارسی (پس از NFKC)
_ARABIC_RANGES = (
    ("\u0620", "\u064a"),   # Arabic
    ("\u066e", "\u06d3"),   # Arabic Supplement / extended
    ("\u06fa", "\u06ff"),
    ("\u0750", "\u077f"),   # Arabic Supplement-B
)
# اعراب و علامت‌های الحاقی مجاز (تشدید، فتحه، کسره، مد و…)
_ARABIC_MARKS = ("\u064b", "\u065f", "\u0670")


def normalize_persian(text: str) -> str:
    """نرمال‌سازی: فرم‌های presentation، حروف عربی→فارسی، فاصله‌ها و نیم‌فاصله."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    s = s.translate(_AR_TO_FA)
    s = _ZERO_WIDTH.sub("", s)
    s = s.replace("\u00a0", " ")          # نستعلیق/nbsp → فاصله
    s = re.sub(r"[ \t]+", " ", s).strip()
    # نیم‌فاصله‌های کنار هم یا ابتدا/انتهای کلمه تمیز می‌شوند
    s = re.sub(rf"{_ZWNJ}+", _ZWNJ, s)
    s = re.sub(rf"{_ZWNJ} ", " ", s)
    s = re.sub(rf" {_ZWNJ}", " ", s)
    s = re.sub(rf"{_ZWNJ}$", "", s)
    s = re.sub(rf"^{_ZWNJ}", "", s)
    return s.strip()


def _is_arabic_letter(ch: str) -> bool:
    return any(lo <= ch <= hi for lo, hi in _ARABIC_RANGES) \
        or (_ARABIC_MARKS[0] <= ch <= _ARABIC_MARKS[1]) or ch == _ARABIC_MARKS[2]


def has_latin(text: str) -> bool:
    """تشخیص واقعی یونیکد: هر حرف لاتین (حتی لهجه‌دار) → True.
    ایموجی، فارسی و علائم ← False."""
    if not text:
        return False
    for ch in str(text):
        if ch.isalpha():
            try:
                if "LATIN" in unicodedata.name(ch, ""):
                    return True
            except ValueError:
                continue
    return False


def validate_persian_name(raw: str):
    """بررسی نام فارسی. خروجی: (ok, normalized_or_error_message).
    پیام خطا در تمام حالت‌های نامعتبر، همان پیام رسمی پروژه است."""
    nick = normalize_persian(raw or "")
    if not nick or nick == _ZWNJ:
        return False, NAME_FA_ERROR
    if not (config.NICK_MIN <= len(nick) <= config.NICK_MAX):
        return False, NAME_FA_ERROR
    for ch in nick:
        if ch == " " or ch == _ZWNJ:
            continue
        if ch.isdigit() or unicodedata.category(ch) == "Nd":
            # هر نوع رقم — فارسی، عربی، لاتین — ممنوع است
            return False, NAME_FA_ERROR
        if not _is_arabic_letter(ch):
            # حروف انگلیسی، علائم و ایموجی رد می‌شوند؛ اعراب (تشدید و…) مجاز
            return False, NAME_FA_ERROR
    return True, nick
