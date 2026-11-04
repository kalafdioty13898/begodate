"""ابزارهای مشترک: نرخ‌گذاری، کارت کاربر، ارسال امن پیام."""
import html
import logging
import time
from collections import defaultdict, deque

import config

log = logging.getLogger("bagoodit")


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=False)


def fmt_coins(n) -> str:
    return f"🪙 {n}"


def chunk(lst, n):
    out = []
    for i in range(0, len(lst), n):
        out.append(lst[i:i + n])
    return out


class RateLimiter:
    """پنجره لغزان در حافظه — جلوگیری از اسپم هر کاربر."""

    def __init__(self, max_msgs: int, window: int):
        self.max = max_msgs
        self.window = window
        self.hits = defaultdict(deque)

    def allow(self, uid: int) -> bool:
        now = time.monotonic()
        dq = self.hits[uid]
        while dq and now - dq[0] > self.window:
            dq.popleft()
        if len(dq) >= self.max:
            return False
        dq.append(now)
        return True


rate_limiter = RateLimiter(config.RATE_LIMIT_MSGS, config.RATE_LIMIT_WINDOW)


def gender_label(g: str) -> str:
    return "👧 دختر" if g == "F" else "👦 پسر"


def gender_emoji(g: str) -> str:
    return "👧" if g == "F" else "👦"


def online_label(state: str) -> str:
    if state == config.ST_CHAT:
        return "💬 در حال چت"
    if state == config.ST_SEARCHING:
        return "📡 در صف جست‌وجو"
    if state == config.ST_NONE:
        return "🆕 ثبت‌نام ناقص"
    return "🟢 آنلاین"


def user_card(user: dict, show_coins=False, show_contact_hint=False) -> str:
    """کارت عمومی پروفایل (HTML)."""
    if not user:
        return "کاربر یافت نشد."
    lines = [f"👤 <b>{esc(user['nickname'] or 'بدون نام')}</b>"]
    lines.append(f"🆔 شناسه ناشناس: <code>{esc(user['bot_user_id'] or '—')}</code>")
    if user["gender"]:
        lines.append(f"🚻 جنسیت: {gender_label(user['gender'])}")
    if user["age"]:
        lines.append(f"🎂 سن: {user['age']}")
    if user["city"]:
        lines.append(f"📍 {esc(user['city'])} — {esc(user['province'] or '')}")
    lines.append(f"🟦 وضعیت: {online_label(user['state'])}")
    if user["is_test_user"]:
        lines.append("🧪 <i>حساب تستی بگودیت</i>")
    if show_coins:
        lines.append(f"🪙 موجودی: <b>{user['coins']}</b> سکه")
    if show_contact_hint:
        lines.append("\n💬 برای شروع چت، دکمه درخواست را بزن.")
    return "\n".join(lines)


async def notify(bot, chat_id: int, text: str, reply_markup=None) -> bool:
    """ارسال امن پیام؛ خطاهای کاربرِ ربات را بلعیده و لاگ می‌کند."""
    try:
        await bot.send_message(chat_id=chat_id, text=text,
                               reply_markup=reply_markup, parse_mode="HTML")
        return True
    except Exception as e:  # Forbidden = کاربر ربات را بلاک کرده
        name = type(e).__name__
        if name not in ("Forbidden",):
            log.warning("notify to %s failed: %s", chat_id, e)
        return False
