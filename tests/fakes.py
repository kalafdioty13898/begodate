"""فیک‌های مشترک تلگرام برای تست‌های سناریویی بگودیت.

این ماژول هیچ وابستگی پروژه‌ای را در سطح ماژول import نمی‌کند تا ترتیب
تنظیم DB_PATH در فایل تست، قبل از import config حفظ شود.
"""
import types


class Sent:
    def __init__(self, text="", markup=None, photo=None):
        self.text, self.markup, self.photo = text, markup, photo


class FakeMessage:
    def __init__(self, text=None, photo=None):
        self.text = text
        self.photo = photo
        self.message_id = id(self) % 100000
        self.outbox = []

    async def reply_text(self, text, parse_mode=None, reply_markup=None, **kw):
        self.outbox.append(Sent(text, reply_markup))
        return self

    async def reply_photo(self, photo=None, caption=None, parse_mode=None,
                          reply_markup=None, **kw):
        self.outbox.append(Sent(caption, reply_markup, photo=photo))
        return self

    async def edit_reply_markup(self, reply_markup=None):
        self.outbox.append(Sent("", reply_markup))
        return self

    @property
    def last(self):
        return self.outbox[-1] if self.outbox else None


def fake_photo(file_id="photo-x"):
    """شیء شبیه PhotoSize تلگرام با file_id."""
    return types.SimpleNamespace(file_id=file_id)


class FakeBot:
    """ربات فیک؛ خطای ارسال به چت مشخص قابل شبیه‌سازی است."""

    def __init__(self):
        self.sent = []            # همه پیام‌های send_message
        self.copies = []          # همه copy_message ها
        self.photos = []          # همه send_photo ها
        self.edits = []           # همه edit_message_text ها
        self.fail_copy_for = set()   # chat_id هایی که copy_message برایشان خطا می‌دهد
        self.fail_copy_exc = None    # نوع استثنا (Forbidden و …)

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None, **kw):
        self.sent.append(Sent(text, reply_markup))
        return types.SimpleNamespace(message_id=len(self.sent) + 100)

    async def send_photo(self, chat_id, photo, caption=None, parse_mode=None,
                         reply_markup=None, **kw):
        self.photos.append(Sent(caption, reply_markup, photo=photo))
        return types.SimpleNamespace(message_id=len(self.photos) + 500)

    async def copy_message(self, chat_id, from_chat_id, message_id, **kw):
        if chat_id in self.fail_copy_for:
            raise (self.fail_copy_exc or RuntimeError("copy failed"))
        self.copies.append({"chat_id": chat_id, "from_chat_id": from_chat_id,
                            "message_id": message_id})

    async def send_media_group(self, chat_id, media, **kw):
        return []

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        self.edits.append(text)
        return True


class FakeJob:
    def __init__(self, data=None):
        self.data = data or {}


class FakeJobQueue:
    def __init__(self, bot=None):
        self.bot = bot
        self.jobs = []

    def run_once(self, callback, when, data=None, name=None):
        self.jobs.append((callback, data or {}, name))

    async def run_all(self):
        """اجرای همه jobهای ثبت‌شده به ترتیب (شبیه‌سازی PTB JobQueue).
        context جاب هم .job و هم .bot دارد (مثل PTB واقعی)."""
        import types
        pending, self.jobs = self.jobs, []
        for cb, data, _name in pending:
            await cb(types.SimpleNamespace(job=FakeJob(data), bot=self.bot))


class FakeCallbackQuery:
    def __init__(self, data: str, uid: int, message: FakeMessage):
        self.data = data
        self.from_user = types.SimpleNamespace(id=uid)
        self.message = message
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class FakeUpdate:
    def __init__(self, uid: int, message: FakeMessage = None, cbq: FakeCallbackQuery = None):
        self.message = message
        self.callback_query = cbq
        self.effective_user = types.SimpleNamespace(id=uid)
        self.effective_chat = types.SimpleNamespace(id=uid)
        self.effective_message = message or (cbq.message if cbq else None)


class FakeContext:
    def __init__(self, admin_id=None):
        self.bot = FakeBot()
        self.args = []
        self.job_queue = FakeJobQueue(self.bot)
        self.error = None


def last_text(msg: FakeMessage) -> str:
    return (msg.last.text if msg.last else "") or ""


def last_markup(msg: FakeMessage):
    return msg.last.markup if msg.last else None


def markup_texts(kb) -> list:
    if kb is None:
        return []
    grid = getattr(kb, "keyboard", None) or getattr(kb, "inline_keyboard", None)
    return [t for row in grid for t in (b.text for b in row)]
