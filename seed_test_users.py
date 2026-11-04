"""ابزار seeding کاربران تستی — مستقل از ربات اجرا می‌شود.
مثال: python seed_test_users.py [--force]
قبل از اجرا مطمئن شو .env (یا متغیرهای محیطی) موجود است."""
import sys

import config
import database as db
from services import test_users


def main() -> None:
    force = "--force" in sys.argv
    config.ensure_dirs()
    db.init()
    existing = db.q1("SELECT COUNT(*) AS c FROM users WHERE is_test_user=1")["c"]
    if existing and not force:
        print(f"✅ {existing} کاربر تستی از قبل موجود است (برای بازسازی: --force).")
        return
    if existing and force:
        n = db.delete_test_users()
        print(f"🗑 {n} کاربر تستی قبلی حذف شد.")
    n = test_users.generate_test_users(force=True)
    print(f"🧪 {n} کاربر تستی ساخته شد "
          f"({config.TEST_USERS_PER_CITY_F} دختر + {config.TEST_USERS_PER_CITY_M} پسر برای هر شهر).")
    print("🖼 برای ساخت آواتارها یک‌بار ربات را اجرا کن و در پنل مدیریت "
          "«🖼 ساخت آواتارها» را بزن (نیاز به /start در چت ادمین دارد).")


if __name__ == "__main__":
    main()
