# 🚀 استقرار بگودیت روی هاست واقعی (VPS اوبونتو)

> ⚠️ **قانون طلایی:** ربات باید **همیشه فقط در یک جا** اجرا شود. دو نمونه همزمان =
> خطای `Conflict: terminated by other getUpdates request` و لگ جدی.

## ۱) انتقال کد

```bash
git clone https://github.com/kalafdioty13898/begodate.git /opt/bagoodit
cd /opt/bagoodit
```

## ۲) محیط مجازی و وابستگی‌ها

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

## ۳) متغیرهای محیطی

```bash
cp .env.example .env
nano .env
```

حداقل این دو مقدار لازم است (بقیه اختیاری‌اند — توضیح در `.env.example`):

```ini
BOT_TOKEN=توکن-از-BotFather
ADMIN_ID=آیدی-عددی-ادمین
```

## ۴) دیتابیس و کاربران تستی (اختیاری)

دیتابیس SQLite خودکار در `data/bagoodit.db` ساخته می‌شود. اگر داده‌ای از قبل
داری، همین فایل را منتقل کن — اسکیما بدون Migration حفظ می‌شود.

```bash
venv/bin/python seed_test_users.py    # ساخت کاربران تستی (اختیاری)
```

## ۵) سرویس systemd (اجرای دائمی + ری‌استارت خودکار)

```bash
cp deploy/bagoodit.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now bagoodit
systemctl status bagoodit
journalctl -u bagoodit -f        # لاگ زنده
```

با هر ری‌بوت سرور، ربات خودش بالا می‌آید؛ با هر کرش، ظرف ۵ ثانیه ری‌استارت می‌شود.

## ۶) به‌روزرسانی نسخه جدید

```bash
cd /opt/bagoodit
git pull
venv/bin/pip install -r requirements.txt   # فقط اگر requirements تغییر کرده
systemctl restart bagoodit
```

## چرا GitHub Actions هاست نمی‌شود؟

- سقف ۶ ساعتی Job و قطعی چندثانیه‌ای بین اجراها → چت‌ها می‌پرند
- خطر اجرای همزمان دو نمونه → Conflict تلگرام
- CI فقط «تست» را اجرا می‌کند که به توکن و دیتابیس واقعی نیاز ندارد
