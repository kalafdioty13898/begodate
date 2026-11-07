"""تاریخ و زمان جلالی + منطقه‌ی زمانی تهران — بدون وابستگی خارجی.

الگوریتم تبدیل: نسخه‌ی دقیق «jalCal» (همان که در jalaali-js / تقویم رسمی
استفاده می‌شود؛ محدوده‌ی معتبر سال ۱۲۰۰ تا ۱۶۳۳ هجری شمسی) — برخلاف
روش ساده‌ی ۳۳ ساله، در سال‌های کبیسه‌ی واقعی خطا ندارد.
ایران از ۱۴۰۱ ساعت تابستانی ندارد؛ آفست ثابت UTC+03:30 است.
"""
from datetime import datetime, timedelta, timezone

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

# نقاط شکست الگوریتم jalCal (سال‌های شمسی)
_BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
           1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]


def to_persian_digits(s) -> str:
    return str(s).translate(_PERSIAN_DIGITS)


def _div(a: int, b: int) -> int:
    """تقسیم صحیح با بریدن به سمت صفر (هم‌رفتاری با jalaali-js)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _mod(a: int, b: int) -> int:
    return a - b * _div(a, b)


def _g2d(gy: int, gm: int, gd: int) -> int:
    """میلادی → شماره‌ی روز ژولینی."""
    d = _div((gy + _div(gm - 8, 6) + 100100) * 1461, 4) \
        + _div(153 * _mod(gm + 9, 12) + 2, 5) + gd - 34840408
    d = d - _div(_div(gy + 100100 + _div(gm - 8, 6), 100) * 3, 4) + 752
    return d


def _d2g(jdn: int):
    """شماره‌ی روز ژولینی → میلادی (gy, gm, gd)."""
    j = 4 * jdn + 139361631
    j = j + _div(_div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
    i = _div(_mod(j, 1461), 4) * 5 + 308
    gd = _div(_mod(i, 153), 5) + 1
    gm = _mod(_div(i, 153), 12) + 1
    gy = _div(j, 1461) - 100100 + _div(8 - gm, 6)
    return gy, gm, gd


def _jal_cal(jy: int):
    """محاسبه‌ی سال شمسی: (leap, gy, march) — march = روز ۱ فروردین در مارس."""
    bl = len(_BREAKS)
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0
    if jy < jp or jy >= _BREAKS[bl - 1]:
        raise ValueError("سال خارج از محدوده‌ی الگوریتم جلالی")
    for i in range(1, bl):
        jm = _BREAKS[i]
        jump = jm - jp
        if jy < jm:
            break
        leap_j = leap_j + _div(jump, 33) * 8 + _div(_mod(jump, 33), 4)
        jp = jm
    n = jy - jp
    leap_j = leap_j + _div(n, 33) * 8 + _div(_mod(n, 33) + 3, 4)
    if _mod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1
    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + _div(jump + 4, 33) * 33
    leap = _mod(_mod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return leap, gy, march


def gregorian_to_jalali(gy: int, gm: int, gd: int):
    """میلادی → جلالی. خروجی: (jy, jm, jd)."""
    jdn = _g2d(gy, gm, gd)
    gyy = _d2g(jdn)[0]
    jy = gyy - 621
    leap, _gy, march = _jal_cal(jy)
    jdn1f = _g2d(gyy, 3, march)
    k = jdn - jdn1f
    if k >= 0:
        if k <= 185:
            return jy, 1 + _div(k, 31), _mod(k, 31) + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if leap == 1:
            k += 1
    return jy, 7 + _div(k, 30), _mod(k, 30) + 1


def jalali_to_gregorian(jy: int, jm: int, jd: int):
    """جلالی → میلادی. خروجی: (gy, gm, gd)."""
    leap, gy, march = _jal_cal(jy)
    jdn = _g2d(gy, 3, march) + (jm - 1) * 31 - _div(jm, 7) * (jm - 7) + jd - 1
    return _d2g(jdn)


def is_jalali_leap(jy: int) -> bool:
    return _jal_cal(jy)[0] == 0


def tehran_tz():
    """منطقه‌ی زمانی تهران؛ در نبود tzdata، آفست ثابت +03:30."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Asia/Tehran")
    except Exception:
        return timezone(timedelta(hours=3, minutes=30), "Tehran")


def tehran_now() -> datetime:
    return datetime.now(tehran_tz())


def _parse_iso_utc(iso_str: str) -> datetime:
    """ISO (با یا بدون آفست) → datetime آگاه به UTC."""
    s = (iso_str or "").strip()
    if not s:
        return tehran_now()
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return tehran_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_jdatetime(iso_utc: str) -> str:
    """ISO UTC → «۱۴۰۵/۰۸/۱۶ - ۱۸:۳۵» به وقت تهران."""
    dt = _parse_iso_utc(iso_utc).astimezone(tehran_tz())
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f"{to_persian_digits(f'{jy}/{jm:02d}/{jd:02d}')} - " \
           f"{to_persian_digits(f'{dt.hour:02d}:{dt.minute:02d}')}"


def fmt_jdate(iso_utc: str) -> str:
    """فقط بخش تاریخ جلالی: «۱۴۰۵/۰۸/۱۶»."""
    dt = _parse_iso_utc(iso_utc).astimezone(tehran_tz())
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return to_persian_digits(f"{jy}/{jm:02d}/{jd:02d}")


def digest_date_key() -> str:
    """کلید «امشب» برای جلوگیری از ارسال دوباره‌ی خلاصه در یک شب (به وقت تهران)."""
    return tehran_now().date().isoformat()
