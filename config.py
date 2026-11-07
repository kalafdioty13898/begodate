"""بگودیت — تنظیمات مرکزی برنامه (بدون هیچ مقدار حساسی در کد)"""
import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# --- اعتبارنامه‌ها (فقط از متغیرهای محیطی / GitHub Secrets) ---
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID") or 0)

# --- مسیرها ---
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.getenv("DB_PATH") or os.path.join(DATA_DIR, "bagoodit.db")

# --- نام کاربری ربات؛ در start-up از getMe پر می‌شود (برای لینک دعوت) ---
BOT_USERNAME = (os.getenv("BOT_USERNAME") or "").strip()

# ================= وضعیت‌های FSM =================
ST_NONE = "NONE"
ST_REG_GENDER = "REGISTER_GENDER"
ST_REG_AGE = "REGISTER_AGE"
ST_REG_PROVINCE = "REGISTER_PROVINCE"
ST_REG_CITY = "REGISTER_CITY"
ST_REG_NICKNAME = "REGISTER_NICKNAME"
ST_REG_PHOTO = "REGISTER_PHOTO"
ST_MAIN = "MAIN_MENU"
ST_MATCH_MENU = "MATCH_MENU"
ST_SEARCHING = "SEARCHING"
ST_CHAT = "IN_CHAT"
ST_FEEDBACK = "FEEDBACK"
ST_SEARCH_USER = "SEARCH_USER"
ST_FILTER = "FILTER_WIZARD"
ST_ADMIN_FIND = "ADMIN_USER_FIND"
ST_ADMIN_COIN = "ADMIN_COIN_ADJ"
ST_ADMIN_MSG = "ADMIN_MSG_USER"
ST_ADMIN_FB = "ADMIN_FB_REPLY"
ST_ADMIN_BC = "ADMIN_BROADCAST"
ST_ADMIN_SET = "ADMIN_SET_VALUE"

# ================= منطقه‌ی زمانی و خلاصه‌ی شبانه =================
TIMEZONE_NAME = (os.getenv("TIMEZONE") or "Asia/Tehran").strip()
DIGEST_SEND_SLEEP = float(os.getenv("DIGEST_SEND_SLEEP", "0.05"))  # فاصله‌ی ارسال‌ها (کنترل سیل)
NOTIF_PAGE_SIZE = 8          # تعداد اعلان در هر صفحه‌ی مرکز اعلان‌ها
NOTIF_BUTTON_TITLE_MAX = 20  # حداکثر طول عنوان اعلان روی دکمه

# ================= محدودیت‌ها =================
AGE_MIN, AGE_MAX = 18, 79
NICK_MIN, NICK_MAX = 2, 30
FEEDBACK_MAX_LEN = 1000
PROV_PAGE_SIZE = 12
CITY_PAGE_SIZE = 16
CARD_TEXT_MAX = 40  # حداکثر طول پیش‌نمایش متن در لیست‌های مدیریت

# ================= نرخ‌گذاری =================
RATE_LIMIT_MSGS = 25
RATE_LIMIT_WINDOW = 15  # ثانیه

BROADCAST_SLEEP = 0.06          # فاصله بین ارسال‌ها (کنترل سیل تلگرام)
BROADCAST_PROGRESS_EVERY = 30   # هر چند ارسال، پیام پیشرفت به‌روز شود

# ================= هزینه پیش‌فرض سکه‌ها =================
COIN_COST_RANDOM = 0  # چت تصادفی همیشه رایگان است

# ================= سیستم کاربران تستی =================
TEST_MODE_ENABLED = (os.getenv("TEST_MODE_ENABLED", "false").strip().lower()
                     in ("1", "true", "yes", "on"))
TEST_MODE_DAYS = int(os.getenv("TEST_MODE_DAYS", "7"))
TEST_USERS_PER_CITY_F = int(os.getenv("TEST_USERS_PER_CITY_F", "20"))
TEST_USERS_PER_CITY_M = int(os.getenv("TEST_USERS_PER_CITY_M", "20"))
TEST_USER_MAX_REPLIES = int(os.getenv("TEST_USER_MAX_REPLIES", "10"))
TEST_REPLY_MIN_DELAY = float(os.getenv("TEST_REPLY_MIN_DELAY", "3"))
TEST_REPLY_MAX_DELAY = float(os.getenv("TEST_REPLY_MAX_DELAY", "10"))
REAL_USERS_FIRST = os.getenv("REAL_USERS_FIRST", "true").strip().lower() in (
    "1", "true", "yes", "on")

# ================= اقتصاد =================
WELCOME_COINS = int(os.getenv("WELCOME_COINS", "5"))
REFERRAL_REWARD = int(os.getenv("REFERRAL_REWARD", "10"))
MATCH_COOLDOWN_MIN = int(os.getenv("MATCH_COOLDOWN_MIN", "720"))  # ۱۲ ساعت

# ================= دلایل گزارش (۷ مورد) =================
REPORT_REASONS = [
    "محتوای نامناسب یا مستهجن",
    "آزار و اذیت",
    "هرزنامه و تبلیغات",
    "کلاهبرداری",
    "تهدید",
    "توهین و بی‌احترامی",
    "سایر دلایل",
]


def ensure_dirs() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
