"""بگودیت — نقطه ورود ربات"""
import asyncio
import logging
import os
import sys

from telegram import BotCommand
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          MessageHandler, filters)

import config
import database as db
from handlers import admin, common

_log_level = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
if _log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
    _log_level = "INFO"
logging.basicConfig(
    level=getattr(logging, _log_level),
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bagoodit")


async def post_init(app: Application) -> None:
    me = await app.bot.get_me()
    config.BOT_USERNAME = me.username
    log.info("bot @%s online", me.username)

    await app.bot.set_my_commands([
        BotCommand("start", "شروع و منوی اصلی"),
        BotCommand("help", "راهنمای بگودیت"),
        BotCommand("cancel", "لغو عملیات جاری"),
    ])

    # استخر آواتارها؛ در اولین اجرا ساخته و به کاربران تستی تخصیص می‌یابد
    from services import test_users as TU
    raw = db.get_setting("avatar_pool")
    if not raw and config.ADMIN_ID:
        try:
            from services import avatars
            pool = await avatars.build_pool(app.bot)
            if pool:
                import json as _json
                db.set_setting("avatar_pool", _json.dumps(pool, ensure_ascii=False))
                log.info("avatar pool built: %s", len(pool))
        except Exception as e:
            log.warning("avatar pool skipped: %s", e)
    else:
        try:
            pool = TU.pool_from_settings()
            if pool:
                n = await asyncio.to_thread(db.assign_avatars_to_tests, pool)
                if n:
                    log.info("avatars assigned to %s test users", n)
        except Exception:
            pass

    # اطلاع به ادمین
    if config.ADMIN_ID:
        try:
            await app.bot.send_message(
                chat_id=config.ADMIN_ID,
                text="🟢 <b>بگودیت آنلاین شد.</b>\nبرای مدیریت: /admin",
                parse_mode="HTML")
        except Exception:
            log.info("admin chat not available yet (باید اول /start بزند)")


def main() -> None:
    if not config.BOT_TOKEN:
        log.critical("BOT_TOKEN تنظیم نشده! فایل .env را بساز.")
        sys.exit(1)
    if not config.ADMIN_ID:
        log.warning("ADMIN_ID تنظیم نشده؛ پنل مدیریت غیرفعال است.")

    config.ensure_dirs()
    db.init()

    app = (Application.builder()
           .token(config.BOT_TOKEN)
           .concurrent_updates(True)
           .post_init(post_init)
           .build())

    # دستورات
    app.add_handler(CommandHandler("start", common.cmd_start))
    app.add_handler(CommandHandler(["cancel", "menu"], common.cmd_cancel))
    app.add_handler(CommandHandler("help", common.cmd_help))
    app.add_handler(CommandHandler("admin", admin.cmd_admin))

    # callbackها
    app.add_handler(CallbackQueryHandler(common.cb_router))

    # پیام‌های خصوصی
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        common.route_text))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.TEXT & ~filters.COMMAND,
        common.route_media))

    # خطای سراسری
    app.add_error_handler(common.error_handler)

    log.info("bagoodit starting polling…")
    app.run_polling(drop_pending_updates=False, allowed_updates=None)


if __name__ == "__main__":
    main()
