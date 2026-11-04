"""تنظیمات قابل تغییر در زمان اجرا (جدول settings) با پیش‌فرض‌های config."""
import config
import database as db

DEFAULTS = {
    "coin_girl": "1",
    "coin_boy": "1",
    "coin_nearby": "3",
    "coin_filter": "4",
    "referral_reward": str(config.REFERRAL_REWARD),
    "welcome_coins": str(config.WELCOME_COINS),
    "match_cooldown_minutes": str(config.MATCH_COOLDOWN_MIN),
    "real_users_first": "true" if config.REAL_USERS_FIRST else "false",
    "test_mode_enabled": "true" if config.TEST_MODE_ENABLED else "false",
    "test_mode_started_at": "",
    "test_mode_expires_at": "",
    "test_mode_manually_disabled": "false",
    "test_mode_days": str(config.TEST_MODE_DAYS),
    "test_user_max_replies": str(config.TEST_USER_MAX_REPLIES),
    "test_reply_min_delay": str(config.TEST_REPLY_MIN_DELAY),
    "test_reply_max_delay": str(config.TEST_REPLY_MAX_DELAY),
}

BOOL_KEYS = {"real_users_first", "test_mode_enabled", "test_mode_manually_disabled"}

# فقط این کلیدها از پنل مدیریت قابل ویرایش‌اند
EDITABLE = {
    "coin_girl": "هزینه جست‌وجوی دختر (سکه)",
    "coin_boy": "هزینه جست‌وجوی پسر (سکه)",
    "coin_nearby": "هزینه افراد نزدیک (سکه)",
    "coin_filter": "هزینه جست‌وجوی پیشرفته (سکه)",
    "referral_reward": "پاداش هر معرفی موفق (سکه)",
    "welcome_coins": "سکه خوش‌آمدگویی",
    "match_cooldown_minutes": "فاصله غیرتکرار تطبیق (دقیقه)",
    "test_mode_days": "مدت تست‌مود (روز)",
    "test_user_max_replies": "حداکثر پاسخ کاربر تستی",
    "test_reply_min_delay": "حداقل تأخیر پاسخ تستی (ثانیه)",
    "test_reply_max_delay": "حداکثر تأخیر پاسخ تستی (ثانیه)",
    "real_users_first": "اولویت کاربران واقعی (true/false)",
}


def get(key: str) -> str:
    v = db.get_setting(key)
    return v if v is not None else DEFAULTS.get(key, "")


def get_int(key: str) -> int:
    try:
        return int(float(get(key)))
    except (ValueError, TypeError):
        return int(float(DEFAULTS.get(key, "0")))


def get_float(key: str) -> float:
    try:
        return float(get(key))
    except (ValueError, TypeError):
        return float(DEFAULTS.get(key, "0"))


def get_bool(key: str) -> bool:
    return get(key).strip().lower() in ("1", "true", "yes", "on")


def set_value(key: str, value) -> None:
    db.set_setting(key, str(value))
