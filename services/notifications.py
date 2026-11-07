"""سرویس اعلان‌های بگودیت.

معماری: هر رویداد مهم «فقط» در دیتابیس ثبت می‌شود (add_notification با
dedup_key ضدتکرار)؛ پیام خلاصه‌ی شبانه ساعت ۰۰:۰۰ به وقت تهران برای هر
کاربرِ دارای اعلان خوانده‌نشده، حداکثر یک‌بار در شب، ارسال می‌شود.
انواع جدید فقط با افزودن به NOTIF_TYPES و یک فراخوانی کمکی قابل توسعه‌اند.
"""
import asyncio
import json
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, RetryAfter, TimedOut

import config
import database as db
from services import settings as S
from utils import jalali as J

log = logging.getLogger("bagoodit.notif")

# type → (آیکون, برچسب) — برای نمایش در مرکز اعلان‌ها
NOTIF_TYPES = {
    "welcome": ("👋", "خوش‌آمدگویی"),
    "chat_request": ("📨", "درخواست چت"),
    "chat_accepted": ("✅", "درخواست قبول شد"),
    "chat_declined": ("❌", "درخواست رد شد"),
    "feedback_reply": ("💬", "پاسخ پشتیبانی"),
    "coin_reward": ("🪙", "پاداش سکه"),
    "referral": ("🎁", "دعوت موفق"),
    "account": ("🛡", "رویداد حساب"),
    "system": ("📢", "اعلان مدیریت"),
}
DIGEST_JOB_NAME = "nightly_digest"


def icon_of(ntype: str) -> str:
    return NOTIF_TYPES.get(ntype, ("🔔", "اعلان"))[0]


def label_of(ntype: str) -> str:
    return NOTIF_TYPES.get(ntype, ("🔔", "اعلان"))[1]


# ---------------- ثبت رویدادها (فراخوانی از هندلرها) ----------------
def ev_chat_request(to_uid: int, rid: int, sender: dict) -> int | None:
    return db.add_notification(
        to_uid, "chat_request",
        "درخواست چت جدید 📨",
        f"«{sender['nickname'] or 'یک کاربر'}» "
        f"(شناسه: {sender['bot_user_id'] or '—'}) برای چت با تو درخواست فرستاده است.\n"
        "برای قبول یا رد، به پیام درخواست در همین گفت‌وگو برو.",
        metadata={"bot_id": sender.get("bot_user_id"), "rid": rid},
        action_type="sender_profile", action_data={"bot_id": sender.get("bot_user_id")},
        dedup_key=f"crq:{rid}")


def ev_chat_accepted(from_uid: int, rid: int) -> int | None:
    return db.add_notification(
        from_uid, "chat_accepted", "درخواست چتت قبول شد ✅",
        "طرف مقابل درخواست تو را قبول کرد؛ چت شروع شده است.\n"
        "اگر چت را بستی، می‌توانی از «💬 چت ناشناس» جست‌وجوی تازه‌ای شروع کنی.",
        dedup_key=f"acc:{rid}")


def ev_chat_declined(from_uid: int, rid: int) -> int | None:
    return db.add_notification(
        from_uid, "chat_declined", "درخواست چتت رد شد ❌",
        "طرف مقابل این‌بار درخواست را نپذیرفت؛ ناراحت نباش!\n"
        "می‌توانی از «🟢 چت تصادفی» با نفر دیگری شروع کنی.",
        dedup_key=f"dec:{rid}")


def ev_feedback_reply(uid: int, fid: int) -> int | None:
    return db.add_notification(
        uid, "feedback_reply", "پاسخ پشتیبانی بگودیت 💬",
        "مدیریت به پیام تو پاسخ داد؛ متن پاسخ در گفت‌وگو ارسال شده است.\n"
        "اگر پاسخ مشخص نیست یا سوالی داری، دوباره از «📝 بازخورد» بنویس.",
        metadata={"fb_id": fid}, action_type="feedback",
        dedup_key=f"fbr:{fid}")


def ev_coin_reward(uid: int, amount: int, reason: str, balance: int) -> int | None:
    if amount <= 0:
        return None
    # رویداد غیرقابل‌تکرار (هر تراکنش یک‌بار در هندلر اجرا می‌شود) → بدون dedup
    return db.add_notification(
        uid, "coin_reward", "پاداش سکه گرفتی 🪙",
        f"🪙 {amount} سکه به موجودی‌ات اضافه شد.\nموجودی فعلی: {balance} سکه",
        metadata={"amount": amount, "reason": reason},
        action_type="balance")


def ev_referral(referrer_uid: int, reward: int, cnt: int, new_uid: int) -> int | None:
    # کلید طبیعی: هر کاربر جدید فقط یک‌بار می‌تواند معرف شود
    return db.add_notification(
        referrer_uid, "referral", "یک دوست با لینک تو اومد 🎁",
        f"🎁 {reward} سکه پاداش دعوت به موجودی‌ات اضافه شد.\n"
        f"📈 مجموع دعوت‌های موفق تو: {cnt}",
        metadata={"count": cnt}, action_type="referral",
        dedup_key=f"ref:{referrer_uid}:{new_uid}")


def ev_account(uid: int, kind: str, title: str, message: str) -> int | None:
    # هر بن/رفع‌بن رویدادی مستقل است → بدون dedup
    return db.add_notification(
        uid, "account", title, message, metadata={"kind": kind},
        action_type="profile")


def ev_system(uid: int, title: str, message: str) -> int | None:
    return db.add_notification(uid, "system", title, message)


# ---------------- خلاصه‌ی شبانه (Scheduler) ----------------
def schedule_digest(job_queue) -> None:
    """ثبت جاب ۰۰:۰۰ تهران — با گارد ضدثبت‌مجدد (شروع‌های چندباره‌ی امن)."""
    if job_queue is None:
        log.warning("job_queue در دسترس نیست؛ خلاصه‌ی شبانه غیرفعال ماند")
        return
    if job_queue.get_jobs_by_name(DIGEST_JOB_NAME):
        log.info("digest job already registered — skipped")
        return
    from datetime import time as dtime
    hour = max(0, min(23, S.get_int("digest_hour")))
    job_queue.run_daily(nightly_digest_job,
                        time=dtime(hour=hour, minute=0, tzinfo=J.tehran_tz()),
                        name=DIGEST_JOB_NAME)
    log.info("nightly digest scheduled at %02d:00 Tehran", hour)


async def _send_digest_message(bot, uid: int, unread: int) -> None:
    """ارسال پیام خلاصه + دکمه‌ی ورود به مرکز اعلان‌ها (با تلاش مجدد کنترل‌شده)."""
    text = (f"🔔 <b>شما اعلان جدید دارید</b>\n"
            f"تعداد اعلان‌های خوانده‌نشده: <b>{unread}</b>")
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔔 خواندن اعلان‌ها", callback_data="nc:open:0")]])
    for attempt in (1, 2):
        try:
            await bot.send_message(chat_id=uid, text=text, parse_mode="HTML",
                                   reply_markup=kb)
            return
        except RetryAfter as e:  # محدودیت نرخ تلگرام — صبر اجباری
            wait = float(getattr(e, "retry_after", 1)) + 1
            log.warning("digest RetryAfter uid=%s wait=%.1fs", uid, wait)
            await asyncio.sleep(wait)
        except TimedOut:
            log.warning("digest TimedOut uid=%s attempt=%s", uid, attempt)
            await asyncio.sleep(2)
        except Forbidden:  # کاربر ربات را بلاک کرده — تلاش بی‌فایده است
            raise
    await bot.send_message(chat_id=uid, text=text, parse_mode="HTML",
                           reply_markup=kb)


async def nightly_digest_job(context) -> None:
    """جاب ۰۰:۰۰ تهران — فقط برای دارندگان اعلان خوانده‌نشده و حداکثر یک‌بار در شب.
    خطای یک کاربر هرگز بقیه را متوقف نمی‌کند؛ همه‌چیز لاگ می‌شود."""
    if not S.get_bool("digest_enabled"):
        log.info("digest disabled by settings — skipped")
        db.log_event("digest", "غیرفعال (تنظیمات)")
        return
    bot = context.bot
    date_key = J.digest_date_key()
    rows = db.users_with_unread()
    sent = skipped_claim = failed = blocked = 0
    for row in rows:
        uid, unread = row["user_id"], row["c"]
        try:
            if not db.claim_digest(uid, date_key, unread):
                skipped_claim += 1  # قبلاً امشب ارسال شده (اجرای دوباره/جاب تکراری)
                continue
            try:
                await _send_digest_message(bot, uid, unread)
                sent += 1
            except Forbidden:
                blocked += 1
            except (RetryAfter, TimedOut) as e:
                failed += 1
                log.warning("digest send failed uid=%s: %s", uid, e)
            except Exception as e:
                failed += 1
                log.warning("digest send error uid=%s: %s", uid, e)
            await asyncio.sleep(config.DIGEST_SEND_SLEEP)
        except Exception as e:  # خطای هر کاربر مستقل است
            failed += 1
            log.exception("digest per-user error uid=%s: %s", uid, e)
    summary = (f"{date_key} | واجد: {len(rows)} | ارسال: {sent} | "
               f"تکرار-شبانه: {skipped_claim} | بلاک: {blocked} | خطا: {failed}")
    log.info("nightly digest done: %s", summary)
    db.log_event("digest", summary)


def digest_schedule_info() -> str:
    enabled = "🟢 فعال" if S.get_bool("digest_enabled") else "🔴 خاموش"
    hour = max(0, min(23, S.get_int("digest_hour")))
    return f"{enabled} | ساعت {J.to_persian_digits(f'{hour:02d}')}:۰۰ تهران"
