"""سرویس سکه‌ها — تمام تغییرات موجودی از طریق database.adjust_coins (اتمیک) می‌گذرد."""
import database as db


def balance(uid: int) -> int:
    return db.get_balance(uid)


def spend(uid: int, amount: int, reason: str):
    """کسر سکه با بررسی موجودی. خروجی: (ok, new_balance)."""
    if amount <= 0:
        return True, db.get_balance(uid)
    bal = db.adjust_coins(uid, -amount, reason)
    if bal is None:
        return False, db.get_balance(uid)
    return True, bal


def earn(uid: int, amount: int, reason: str) -> int:
    if amount <= 0:
        return db.get_balance(uid)
    return db.adjust_coins(uid, amount, reason) or 0


def refund(uid: int, amount: int, reason: str) -> int:
    if amount <= 0:
        return db.get_balance(uid)
    return db.adjust_coins(uid, amount, f"refund:{reason}") or 0
