"""تولید آواتار گرافیکی (بدون عکس واقعی انسان) با Pillow + ساخت استخر آواتار در تلگرام.
آواتارها فقط الگوی هندسی رنگی هستند؛ به هیچ وجه عکس آدم‌ها نیست."""
import logging
import math
import os
import random

import config

log = logging.getLogger("bagoodit.avatars")

try:
    from PIL import Image, ImageDraw
    PIL_OK = True
except ImportError:  # pragma: no cover
    PIL_OK = False

F_PALETTES = [
    ((244, 143, 177), (251, 207, 232)), ((240, 98, 146), (255, 224, 178)),
    ((186, 104, 200), (247, 198, 236)), ((255, 112, 67), (255, 213, 79)),
    ((206, 147, 216), (225, 190, 231)), ((233, 30, 99), (249, 168, 212)),
]
M_PALETTES = [
    ((66, 165, 245), (129, 212, 250)), ((38, 166, 154), (128, 222, 234)),
    ((92, 107, 192), (159, 168, 218)), ((0, 137, 123), (77, 208, 225)),
    ((67, 160, 71), (165, 214, 167)), ((255, 167, 38), (255, 224, 130)),
]

SIZE = 512
AVATAR_COUNT = 60  # ۳۰ برای هر جنسیت


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def generate_one(idx: int, gender: str, path: str) -> str:
    rng = random.Random(f"bagoodit-{gender}-{idx}")
    palettes = F_PALETTES if gender == "F" else M_PALETTES
    c1, c2 = rng.choice(palettes)
    img = Image.new("RGB", (SIZE, SIZE))
    dr = ImageDraw.Draw(img, "RGBA")
    # پس‌زمینه گرادیان عمودی
    for y in range(SIZE):
        dr.line([(0, y), (SIZE, y)], fill=_lerp(c1, c2, y / SIZE))
    # لایه اشکال هندسی نیمه‌شفاف
    shapes = rng.randint(5, 8)
    for _ in range(shapes):
        r = rng.randint(60, 190)
        x = rng.randint(-40, SIZE + 40)
        y = rng.randint(-40, SIZE + 40)
        alpha = rng.randint(35, 85)
        shade = rng.choice([(255, 255, 255), (30, 30, 60)])
        kind = rng.choice(["circle", "ring", "tri"])
        if kind == "circle":
            dr.ellipse([x - r, y - r, x + r, y + r], fill=shade + (alpha,))
        elif kind == "ring":
            w = rng.randint(10, 30)
            dr.ellipse([x - r, y - r, x + r, y + r], outline=shade + (alpha,),
                       width=w)
        else:
            pts = []
            for k in range(3):
                ang = math.pi * 2 * k / 3 + rng.uniform(-0.4, 0.4)
                pts.append((x + r * math.cos(ang), y + r * math.sin(ang)))
            dr.polygon(pts, fill=shade + (alpha,))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG")
    return path


def generate_all() -> list:
    """تولید همه فایل‌ها؛ خروجی: [(gender, path), ...]"""
    out = []
    for i in range(AVATAR_COUNT // 2):
        out.append(("F", generate_one(i, "F",
                                      os.path.join(config.DATA_DIR, "avatars",
                                                   f"avatar_f_{i:02d}.png"))))
        out.append(("M", generate_one(i, "M",
                                      os.path.join(config.DATA_DIR, "avatars",
                                                   f"avatar_m_{i:02d}.png"))))
    return out


async def build_pool(bot) -> list:
    """تولید و بارگذاری آواتارها در چت ادمین برای گرفتن file_id (یک‌بار برای همیشه).
    خروجی: [{"g": "F"/"M", "file_id": ...}, ...] یا [] در صورت خطا."""
    if not PIL_OK:
        log.warning("Pillow نصب نیست؛ استخر آواتار ساخته نشد.")
        return []
    av_dir = os.path.join(config.DATA_DIR, "avatars")
    os.makedirs(av_dir, exist_ok=True)
    files = generate_all()
    pool = []
    for g in ("F", "M"):
        batch = [(gg, p) for gg, p in files if gg == g]
        for i in range(0, len(batch), 10):
            chunk_ = batch[i:i + 10]
            media = []
            from telegram import InputMediaPhoto
            handles = []
            try:
                for gg, path in chunk_:
                    fh = open(path, "rb")
                    handles.append(fh)
                    media.append(InputMediaPhoto(fh))
                msgs = await bot.send_media_group(chat_id=config.ADMIN_ID, media=media)
                for m in msgs:
                    fid = m.photo[-1].file_id if m.photo else None
                    if fid:
                        pool.append({"g": g, "file_id": fid})
            except Exception as e:
                log.warning("avatar upload failed: %s (اگر ادمین هنوز /start نزده طبیعی است)", e)
                pool = []
                break
            finally:
                for fh in handles:
                    fh.close()
            if not pool:
                break
        if not pool:
            break
    return pool
