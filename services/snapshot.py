"""Snapshot JSON — ذخیره‌سازی داده‌ها برای هفته‌ی اول (اجرای ابری بدون دیسک پایدار).
SQLite مرجع اصلی است؛ این ماژول یک کپی JSON کامل می‌سازد و در استارتِ
دیتابیسِ خالی، آن را برمی‌گرداند. روی هاست واقعی هم به‌عنوان Backup/Restore کار می‌کند.
"""
import json
import logging
import os
from datetime import datetime, timezone

import config
import database as db

log = logging.getLogger("bagoodit.snapshot")

TABLES = ["users", "chats", "chat_requests", "reports", "transactions",
          "feedback", "match_history", "settings", "chat_messages", "audit_log"]


def snapshot_path() -> str:
    return os.getenv("SNAPSHOT_PATH") or os.path.join(config.DATA_DIR, "snapshot.json")


def export_to(path: str = None) -> dict:
    """خروجی کامل دیتابیس به یک فایل JSON (اتمیک: اول فایل موقت، بعد جایگزینی)."""
    path = path or snapshot_path()
    data = {
        "_meta": {
            "version": 2,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "counts": {},
        }
    }
    for t in TABLES:
        rows = db.q(f"SELECT * FROM {t}")
        data[t] = rows
        data["_meta"]["counts"][t] = len(rows)
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return data["_meta"]["counts"]


def restore_if_empty(path: str = None) -> dict:
    """اگر دیتابیس خالی باشد (بدون کاربر)، Snapshot را برمی‌گرداند.
    هرگز داده‌ی موجود را بازنویسی نمی‌کند."""
    path = path or snapshot_path()
    have = db.q1("SELECT COUNT(*) AS c FROM users")["c"]
    if have > 0:
        return {"restored": False, "reason": "db not empty", "users": have}
    if not os.path.exists(path):
        return {"restored": False, "reason": "no snapshot file"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError) as e:
        log.warning("snapshot restore failed: %s", e)
        return {"restored": False, "reason": f"corrupt: {e}"}
    with db._lock:
        try:
            for t in TABLES:
                rows = data.get(t) or []
                if not rows:
                    continue
                cols = list(rows[0].keys())
                sql = (f"INSERT INTO {t} ({', '.join(cols)}) "
                       f"VALUES ({', '.join('?' for _ in cols)})")
                db._conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
            db._conn.commit()
        except Exception as e:
            db._conn.rollback()
            log.warning("snapshot restore rolled back: %s", e)
            return {"restored": False, "reason": f"error: {e}"}
    users = db.q1("SELECT COUNT(*) AS c FROM users")["c"]
    log.info("snapshot restored: %s users", users)
    return {"restored": True, "users": users}


def export_if_enabled() -> dict:
    """فقط وقتی SNAPSHOT_ENABLED فعال است خروجی می‌گیرد (پیش‌فرض: روشن)."""
    if (os.getenv("SNAPSHOT_ENABLED", "true").strip().lower()
            in ("0", "false", "no", "off")):
        return {}
    try:
        return export_to()
    except Exception as e:
        log.warning("snapshot export failed: %s", e)
        return {}
