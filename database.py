"""لایه دسترسی به داده — SQLite با قفل سراسری و تراکنش اتمیک.
طراحی ماژولار: تمام کوئری‌ها از همین فایل می‌گذرند تا بعداً بتوان
با حداقل تغییر، PostgreSQL را جایگزین کرد."""
import json
import os
import random
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import config

_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id    INTEGER PRIMARY KEY,
    bot_user_id    TEXT UNIQUE,
    nickname       TEXT,
    gender         TEXT,
    age            INTEGER,
    province       TEXT,
    city           TEXT,
    avatar_file_id TEXT,
    coins          INTEGER NOT NULL DEFAULT 0,
    state          TEXT NOT NULL DEFAULT 'NONE',
    context        TEXT NOT NULL DEFAULT '{}',
    banned         INTEGER NOT NULL DEFAULT 0,
    is_test_user   INTEGER NOT NULL DEFAULT 0,
    referred_by    INTEGER,
    created_at     TEXT NOT NULL,
    last_active    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_state ON users(state);
CREATE INDEX IF NOT EXISTS idx_users_city  ON users(city);
CREATE INDEX IF NOT EXISTS idx_users_test  ON users(is_test_user);

CREATE TABLE IF NOT EXISTS chats (
    chat_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user1_id          INTEGER NOT NULL,
    user2_id          INTEGER NOT NULL,
    init_kind         TEXT,
    is_test_chat      INTEGER NOT NULL DEFAULT 0,
    state             TEXT NOT NULL DEFAULT 'ACTIVE',
    test_replies_used INTEGER NOT NULL DEFAULT 0,
    test_replies_max  INTEGER,
    last_reply        TEXT,
    started_at        TEXT NOT NULL,
    ended_at          TEXT,
    closer_id         INTEGER
);
CREATE INDEX IF NOT EXISTS idx_chats_state ON chats(state);

CREATE TABLE IF NOT EXISTS chat_requests (
    request_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    from_uid    INTEGER NOT NULL,
    to_uid      INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'PENDING',
    created_at  TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_crq_to ON chat_requests(to_uid, status);

CREATE TABLE IF NOT EXISTS reports (
    report_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER NOT NULL,
    reported_id INTEGER NOT NULL,
    chat_id     INTEGER,
    reason      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'OPEN',
    created_at  TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    tx_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    amount        INTEGER NOT NULL,
    reason        TEXT,
    balance_after INTEGER,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id);

CREATE TABLE IF NOT EXISTS feedback (
    fb_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'OPEN',
    admin_reply TEXT,
    created_at  TEXT NOT NULL,
    answered_at TEXT
);

CREATE TABLE IF NOT EXISTS match_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user1_id   INTEGER NOT NULL,
    user2_id   INTEGER NOT NULL,
    matched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mh_pair ON match_history(user1_id, user2_id, matched_at);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init() -> None:
    global _conn
    if _conn is not None:
        return
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA busy_timeout=5000")
    _conn.executescript(SCHEMA)
    _conn.commit()


# ---------------- پایه ----------------
def q(sql: str, params=()) -> list:
    with _lock:
        cur = _conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def q1(sql: str, params=()):
    rows = q(sql, params)
    return rows[0] if rows else None


def x(sql: str, params=()) -> int:
    with _lock:
        cur = _conn.execute(sql, params)
        _conn.commit()
        return cur.rowcount


# ---------------- کاربران ----------------
def ensure_user(tid: int) -> dict:
    """ساخت ردیف کاربر در اولین تماس + سکه خوش‌آمدگویی (فقط یک‌بار)."""
    u = get_user(tid)
    if u:
        return u
    with _lock:
        u = q1("SELECT * FROM users WHERE telegram_id=?", (tid,))
        if u:
            return u
        _conn.execute(
            "INSERT INTO users (telegram_id, coins, created_at, last_active) "
            "VALUES (?,?,?,?)", (tid, 0, now_iso(), now_iso()))
        if config.WELCOME_COINS > 0:
            _conn.execute("UPDATE users SET coins=? WHERE telegram_id=?",
                          (config.WELCOME_COINS, tid))
            _conn.execute(
                "INSERT INTO transactions (user_id, amount, reason, balance_after, created_at) "
                "VALUES (?,?,?,?,?)",
                (tid, config.WELCOME_COINS, "welcome", config.WELCOME_COINS, now_iso()))
        _conn.commit()
    return get_user(tid)


def get_user(tid: int):
    return q1("SELECT * FROM users WHERE telegram_id=?", (tid,))


def get_user_by_bot_id(bot_id: str):
    return q1("SELECT * FROM users WHERE bot_user_id=?", (bot_id,))


_ALLOWED_COLS = {"bot_user_id", "nickname", "gender", "age", "province", "city",
                 "avatar_file_id", "coins", "state", "context", "banned",
                 "is_test_user", "referred_by"}


def update_user(tid: int, **fields) -> None:
    keys = [k for k in fields if k in _ALLOWED_COLS]
    if not keys:
        return
    sets, vals = [], []
    for k in keys:
        v = fields[k]
        if k == "context" and not isinstance(v, str):
            v = json.dumps(v, ensure_ascii=False)
        sets.append(f"{k}=?")
        vals.append(v)
    vals.extend([now_iso(), tid])
    x(f"UPDATE users SET {', '.join(sets)}, last_active=? WHERE telegram_id=?", vals)


def set_state(tid: int, state: str, ctx=None) -> None:
    update_user(tid, state=state, context=ctx if ctx is not None else {})


def get_ctx(user: dict) -> dict:
    try:
        return json.loads(user.get("context") or "{}")
    except (ValueError, TypeError):
        return {}


def is_registered(user) -> bool:
    return bool(user and user["nickname"] and user["gender"] and user["age"]
                and user["province"] and user["city"])


def gen_bot_user_id(gender: str) -> str:
    """شناسه ناشناس: user5XXXX برای دختر، user4XXXX برای پسر (یکتا)."""
    lo, hi = (50000, 59999) if gender == "F" else (40000, 49999)
    for _ in range(200):
        n = random.randint(lo, hi)
        bot_id = f"user{n}"
        if not q1("SELECT 1 FROM users WHERE bot_user_id=?", (bot_id,)):
            return bot_id
    for n in range(lo, hi + 1):  # فضای کامل در حالت فشار
        bot_id = f"user{n}"
        if not q1("SELECT 1 FROM users WHERE bot_user_id=?", (bot_id,)):
            return bot_id
    raise RuntimeError("bot_user_id space exhausted")


def list_state(state: str) -> list:
    return q("SELECT * FROM users WHERE state=? AND banned=0", (state,))


def all_real_user_ids() -> list:
    return [r["telegram_id"] for r in
            q("SELECT telegram_id FROM users WHERE banned=0 AND is_test_user=0 "
              "AND telegram_id>0")]


def search_user_any(query: str):
    """جست‌وجوی کاربر با آیدی عددی یا شناسه ناشناس."""
    query = (query or "").strip().lstrip("/").lower()
    if query.isdigit():
        return get_user(int(query))
    if query.startswith("user") and query[4:].isdigit():
        return get_user_by_bot_id(query)
    return None


# ---------------- سکه‌ها ----------------
def adjust_coins(tid: int, delta: int, reason: str, allow_negative=False):
    """تغییر اتمیک موجودی + ثبت تراکنش. در کمبود موجودی None برمی‌گرداند."""
    with _lock:
        if delta < 0 and not allow_negative:
            row = _conn.execute("SELECT coins FROM users WHERE telegram_id=?",
                                (tid,)).fetchone()
            if not row or row["coins"] + delta < 0:
                return None
        cur = _conn.execute("UPDATE users SET coins=coins+? WHERE telegram_id=?",
                            (delta, tid))
        if cur.rowcount != 1:
            _conn.rollback()
            return None
        bal = _conn.execute("SELECT coins FROM users WHERE telegram_id=?",
                            (tid,)).fetchone()["coins"]
        _conn.execute(
            "INSERT INTO transactions (user_id, amount, reason, balance_after, created_at) "
            "VALUES (?,?,?,?,?)", (tid, delta, reason, bal, now_iso()))
        _conn.commit()
        return bal


def get_balance(tid: int) -> int:
    u = get_user(tid)
    return u["coins"] if u else 0


def user_transactions(tid: int, limit=10) -> list:
    return q("SELECT * FROM transactions WHERE user_id=? ORDER BY tx_id DESC LIMIT ?",
             (tid, limit))


# ---------------- چت و صف ----------------
def pair_users(uid_a: int, uid_b: int, init_kind: str, b_is_test=False,
               test_replies_cap=None):
    """اتصال اتمیک دو کاربر؛ جلوگیری از race-condition با شرط وضعیت.
    اگر هر یک از طرفین در چت دیگری باشد یا بن باشد، None برمی‌گرداند."""
    with _lock:
        cur = _conn.execute(
            "UPDATE users SET state=?, context='{}', last_active=? "
            "WHERE telegram_id=? AND banned=0 AND state!='IN_CHAT'",
            (config.ST_CHAT, now_iso(), uid_a))
        ok_a = cur.rowcount == 1
        if b_is_test:
            cur = _conn.execute(
                "UPDATE users SET state=?, context='{}' "
                "WHERE telegram_id=? AND is_test_user=1 AND state!='IN_CHAT'",
                (config.ST_CHAT, uid_b))
        else:
            cur = _conn.execute(
                "UPDATE users SET state=?, context='{}', last_active=? "
                "WHERE telegram_id=? AND banned=0 AND state!='IN_CHAT'",
                (config.ST_CHAT, now_iso(), uid_b))
        ok_b = cur.rowcount == 1
        if not (ok_a and ok_b):
            _conn.rollback()
            return None
        cap = test_replies_cap if b_is_test else None
        cur = _conn.execute(
            "INSERT INTO chats (user1_id, user2_id, init_kind, is_test_chat, "
            "test_replies_used, test_replies_max, started_at) "
            "VALUES (?,?,?,?,0,?,?)",
            (uid_a, uid_b, init_kind, 1 if b_is_test else 0, cap, now_iso()))
        cid = cur.lastrowid
        _conn.execute(
            "INSERT INTO match_history (user1_id, user2_id, matched_at) "
            "VALUES (?,?,?)", (min(uid_a, uid_b), max(uid_a, uid_b), now_iso()))
        _conn.commit()
        return cid


def get_chat(chat_id: int):
    return q1("SELECT * FROM chats WHERE chat_id=?", (chat_id,))


def get_active_chat(uid: int):
    return q1("SELECT * FROM chats WHERE state='ACTIVE' AND (user1_id=? OR user2_id=?)",
              (uid, uid))


def close_chat(chat_id: int, closer_id=None):
    """بستن چت + بازگرداندن هر دو کاربر به منوی اصلی. خروجی: (u1, u2) یا None."""
    with _lock:
        ch = _conn.execute("SELECT * FROM chats WHERE chat_id=? AND state='ACTIVE'",
                           (chat_id,)).fetchone()
        if not ch:
            return None
        _conn.execute("UPDATE chats SET state='CLOSED', ended_at=?, closer_id=? "
                      "WHERE chat_id=?", (now_iso(), closer_id, chat_id))
        _conn.execute("UPDATE users SET state=?, context='{}' "
                      "WHERE telegram_id IN (?,?) AND state=?",
                      (config.ST_MAIN, ch["user1_id"], ch["user2_id"], config.ST_CHAT))
        _conn.commit()
        return (ch["user1_id"], ch["user2_id"])


def partner_id_of(chat: dict, uid: int) -> int:
    return chat["user2_id"] if chat["user1_id"] == uid else chat["user1_id"]


def bump_test_reply(chat_id: int) -> int:
    """افزایش شمارنده پاسخ‌های کاربر تستی؛ مقدار جدید را برمی‌گرداند."""
    with _lock:
        _conn.execute("UPDATE chats SET test_replies_used=test_replies_used+1 "
                      "WHERE chat_id=?", (chat_id,))
        _conn.commit()
        row = _conn.execute("SELECT test_replies_used FROM chats WHERE chat_id=?",
                            (chat_id,)).fetchone()
        return row["test_replies_used"] if row else 0


def set_last_reply(chat_id: int, text: str) -> None:
    x("UPDATE chats SET last_reply=? WHERE chat_id=?", (text, chat_id))


def user_chats(uid: int, limit=10) -> list:
    rows = q("SELECT * FROM chats WHERE user1_id=? OR user2_id=? "
             "ORDER BY chat_id DESC LIMIT ?", (uid, uid, limit))
    for r in rows:
        r["partner"] = r["user2_id"] if r["user1_id"] == uid else r["user1_id"]
    return rows


def active_chats_list() -> list:
    return q("SELECT * FROM chats WHERE state='ACTIVE' ORDER BY chat_id DESC")


# ---------------- تاریخچه تطبیق ----------------
def was_recently_matched(a: int, b: int, minutes: int) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(
        timespec="seconds")
    row = q1("SELECT 1 FROM match_history WHERE user1_id=? AND user2_id=? AND matched_at>?",
             (min(a, b), max(a, b), cutoff))
    return row is not None


# ---------------- درخواست چت ----------------
def create_chat_request(from_uid: int, to_uid: int):
    """ساخت درخواست جدید؛ اگر درخواست در انتظار مشابه باشد None."""
    if from_uid == to_uid:
        return None
    dup = q1("SELECT 1 FROM chat_requests WHERE from_uid=? AND to_uid=? AND status='PENDING'",
             (from_uid, to_uid))
    if dup:
        return None
    x("INSERT INTO chat_requests (from_uid, to_uid, status, created_at) "
      "VALUES (?,?,'PENDING',?)", (from_uid, to_uid, now_iso()))
    row = q1("SELECT request_id FROM chat_requests WHERE from_uid=? AND to_uid=? "
             "AND status='PENDING' ORDER BY request_id DESC", (from_uid, to_uid))
    return row["request_id"] if row else None


def get_request(rid: int):
    return q1("SELECT * FROM chat_requests WHERE request_id=?", (rid,))


def set_request_status(rid: int, status: str) -> bool:
    return x("UPDATE chat_requests SET status=?, resolved_at=? "
             "WHERE request_id=? AND status='PENDING'", (status, now_iso(), rid)) == 1


# ---------------- گزارش‌ها ----------------
def add_report(reporter: int, reported: int, chat_id, reason: str) -> int:
    x("INSERT INTO reports (reporter_id, reported_id, chat_id, reason, created_at) "
      "VALUES (?,?,?,?,?)", (reporter, reported, chat_id, reason, now_iso()))
    row = q1("SELECT report_id FROM reports WHERE reporter_id=? AND reported_id=? "
             "ORDER BY report_id DESC", (reporter, reported))
    return row["report_id"] if row else 0


def get_report(rid: int):
    return q1("SELECT * FROM reports WHERE report_id=?", (rid,))


def open_reports(limit=20) -> list:
    return q("SELECT * FROM reports WHERE status='OPEN' ORDER BY report_id DESC LIMIT ?",
             (limit,))


def resolve_report(rid: int) -> bool:
    return x("UPDATE reports SET status='RESOLVED', resolved_at=? WHERE report_id=?",
             (now_iso(), rid)) == 1


# ---------------- بازخورد ----------------
def add_feedback(uid: int, text: str) -> int:
    x("INSERT INTO feedback (user_id, text, created_at) VALUES (?,?,?)",
      (uid, text, now_iso()))
    row = q1("SELECT fb_id FROM feedback WHERE user_id=? ORDER BY fb_id DESC", (uid,))
    return row["fb_id"] if row else 0


def get_feedback(fid: int):
    return q1("SELECT * FROM feedback WHERE fb_id=?", (fid,))


def open_feedback(limit=20) -> list:
    return q("SELECT * FROM feedback WHERE status='OPEN' ORDER BY fb_id DESC LIMIT ?",
             (limit,))


def answer_feedback(fid: int, reply: str) -> bool:
    return x("UPDATE feedback SET status='ANSWERED', admin_reply=?, answered_at=? "
             "WHERE fb_id=?", (reply, now_iso(), fid)) == 1


# ---------------- تنظیمات ----------------
def get_setting(key: str, default=None):
    row = q1("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value) -> None:
    x("INSERT INTO settings (key, value) VALUES (?,?) "
      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def all_settings() -> dict:
    return {r["key"]: r["value"] for r in q("SELECT * FROM settings")}


# ---------------- معرفی (Referral) ----------------
def bind_referral(new_user_tid: int, referrer_tid: int) -> bool:
    """اتصال معرف فقط یک‌بار و فقط اگر خودی نباشد."""
    if new_user_tid == referrer_tid:
        return False
    referrer = get_user(referrer_tid)
    if not referrer or referrer["banned"]:
        return False
    return x("UPDATE users SET referred_by=? WHERE telegram_id=? AND referred_by IS NULL",
             (referrer_tid, new_user_tid)) == 1


def referral_count(tid: int) -> int:
    row = q1("SELECT COUNT(*) AS c FROM users WHERE referred_by=?", (tid,))
    return row["c"] if row else 0


def top_referrers(limit=10) -> list:
    return q("SELECT referred_by AS tid, COUNT(*) AS c FROM users "
             "WHERE referred_by IS NOT NULL GROUP BY referred_by "
             "ORDER BY c DESC LIMIT ?", (limit,))


# ---------------- آمار و مدیریت ----------------
def stats() -> dict:
    s = {}
    s["users_total"] = q1("SELECT COUNT(*) AS c FROM users")["c"]
    s["users_real"] = q1("SELECT COUNT(*) AS c FROM users WHERE is_test_user=0 AND telegram_id>0")["c"]
    s["users_test"] = q1("SELECT COUNT(*) AS c FROM users WHERE is_test_user=1")["c"]
    s["male"] = q1("SELECT COUNT(*) AS c FROM users WHERE gender='M'")["c"]
    s["female"] = q1("SELECT COUNT(*) AS c FROM users WHERE gender='F'")["c"]
    s["chats_active"] = q1("SELECT COUNT(*) AS c FROM chats WHERE state='ACTIVE'")["c"]
    s["chats_total"] = q1("SELECT COUNT(*) AS c FROM chats")["c"]
    s["queue"] = q1("SELECT COUNT(*) AS c FROM users WHERE state=?", (config.ST_SEARCHING,))["c"]
    s["reports_open"] = q1("SELECT COUNT(*) AS c FROM reports WHERE status='OPEN'")["c"]
    s["feedback_open"] = q1("SELECT COUNT(*) AS c FROM feedback WHERE status='OPEN'")["c"]
    s["referrals_total"] = q1("SELECT COUNT(*) AS c FROM users WHERE referred_by IS NOT NULL")["c"]
    row = q1("SELECT COALESCE(SUM(amount),0) AS s FROM transactions WHERE amount>0")
    s["coins_granted"] = row["s"]
    return s


def test_users_list(limit=100) -> list:
    return q("SELECT * FROM users WHERE is_test_user=1 LIMIT ?", (limit,))


def delete_test_users() -> int:
    """حذف فقط کاربران تستی + بستن چت‌های مرتبط + پاک‌سازی تاریخچه تطبیق آن‌ها."""
    with _lock:
        rows = _conn.execute(
            "SELECT chat_id, user1_id, user2_id FROM chats WHERE state='ACTIVE' "
            "AND (user1_id<0 OR user2_id<0)").fetchall()
        for r in rows:
            _conn.execute("UPDATE chats SET state='CLOSED', ended_at=? WHERE chat_id=?",
                          (now_iso(), r["chat_id"]))
            real = r["user1_id"] if r["user1_id"] > 0 else r["user2_id"]
            _conn.execute("UPDATE users SET state=?, context='{}' WHERE telegram_id=? "
                          "AND state=?", (config.ST_MAIN, real, config.ST_CHAT))
        n = _conn.execute("DELETE FROM users WHERE is_test_user=1").rowcount
        _conn.execute("DELETE FROM match_history WHERE user1_id<0 OR user2_id<0")
        _conn.commit()
        return n


def assign_avatars_to_tests(pool: list) -> int:
    """تخصیص تصادفی آواتار (هم‌جنس) به کاربران تستی بدون عکس."""
    f_pool = [p["file_id"] for p in pool if p.get("g") == "F"]
    m_pool = [p["file_id"] for p in pool if p.get("g") == "M"]
    n = 0
    for u in q("SELECT telegram_id, gender FROM users WHERE is_test_user=1 "
               "AND (avatar_file_id IS NULL OR avatar_file_id='')"):
        src = f_pool if u["gender"] == "F" else m_pool
        if not src:
            src = f_pool + m_pool
        if src:
            x("UPDATE users SET avatar_file_id=? WHERE telegram_id=?",
              (random.choice(src), u["telegram_id"]))
            n += 1
    return n
