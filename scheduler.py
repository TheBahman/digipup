"""زمان‌بند بررسی قیمت‌های Digipup.

کارکرد:
- یک جاب دوره‌ای (هر SCHEDULER_TICK_SECONDS ثانیه، پیش‌فرض ۶۰) اجرا می‌شود.
- محصولاتی که موعد بررسی‌شان رسیده (بازه + jitter تصادفی ±۳۰ ثانیه) پیدا می‌شوند.
- برای هر محصول آخرین قیمت از price_history خوانده می‌شود، قیمت جدید گرفته و
  رکورد جدید ذخیره می‌شود.
- در صورت تغییر قیمت، درصد تغییر با فرمول ((جدید - قبلی) / قبلی) * 100 محاسبه
  و پیام قالب‌بندی‌شده (ایموجی + اعداد فارسی) فرستاده می‌شود.
- اگر قیمت تغییر نکرد پیامی فرستاده نمی‌شود، مگر NOTIFY_ON_NO_CHANGE=true باشد.

ایمنی‌ها:
- قفل درون‌حافظه‌ای جلوی اجرای هم‌زمان تکراری برای یک محصول را می‌گیرد
  (هم بررسی خودکار، هم بررسی فوری دستی).
- خطاهای استخراج بدون کرش مدیریت می‌شوند؛ برای جلوگیری از اسپم، پیام خطا فقط
  در اولین خطا و هر ERROR_NOTIFY_EVERY خطای متوالی فرستاده می‌شود.
- اگر کاربر ربات را بلاک کرده باشد، رصد آن محصول به‌طور خودکار غیرفعال می‌شود.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import timedelta

from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

import utils
from config import Config
from db import Database
from scraper import BaseScraper, ProductUnavailable, ScrapeError

log = logging.getLogger("digipup.scheduler")

# پیام‌های خطا (طبق قالب تعریف‌شده‌ی پروژه)
ERR_EXTRACT = "⚠️ فعلاً نتوانستم قیمت را بخوانم. کمی بعد دوباره تلاش می‌کنم."
ERR_BLOCKED = "🚫 سایت پاسخ معتبر نداد؛ بررسی بعدی طبق زمان‌بندی انجام می‌شود."
BUSY_TEXT = "⏳ بررسی قبلی این محصول هنوز در جریان است؛ چند لحظه‌ی دیگر دوباره امتحان کن."

# ---------------- وضعیت درون‌حافظه‌ای (با ری‌استارت ربات صفر می‌شود) --------
_busy: set[int] = set()            # شناسه‌ی محصولاتی که همین حالا در حال بررسی‌اند
_fail_counts: dict[int, int] = {}  # شمارش خطاهای متوالی هر محصول
_state: dict[int, str] = {}        # آخرین وضعیت موجودی هر محصول: ok / unavailable


# ---------------------------------------------------------------------------
# زمان‌بندی
# ---------------------------------------------------------------------------


def is_due(product: dict, now, cfg: Config) -> bool:
    """آیا موعد بررسی این محصول رسیده است؟ (بازه + jitter تصادفی)"""
    if not product.get("is_active"):
        return False
    last = utils.parse_utc(product.get("last_checked_at"))
    if last is None:
        return True  # هرگز بررسی نشده
    interval = timedelta(
        minutes=max(cfg.min_interval_minutes, int(product["interval_minutes"]))
    )
    # earliest = بازه منهای jitter (نزدیک‌ترین لحظه‌ی ممکن)
    earliest = last + interval - timedelta(seconds=cfg.jitter_seconds)
    if now < earliest:
        return False
    # jitter تصادفی بین 0 تا 2×JITTER (یعنی ±JITTER حول بازه)
    due_at = earliest + timedelta(seconds=random.uniform(0, 2 * cfg.jitter_seconds))
    return now >= due_at


# ---------------------------------------------------------------------------
# هسته‌ی بررسی یک محصول
# ---------------------------------------------------------------------------


async def check_product(
    cfg: Config,
    db: Database,
    scraper: BaseScraper,
    product: dict,
    *,
    manual: bool = False,
) -> str | None:
    """یک بررسی کامل قیمت؛ متن پیام قابل ارسال را برمی‌گرداند یا None.

    manual=True: نتیجه همیشه به‌صورت متن برمی‌گردد (برای «بررسی فوری»).
    """
    pid = int(product["id"])
    if pid in _busy:
        # جلوی اجرای هم‌زمان تکراری برای یک محصول
        return BUSY_TEXT if manual else None
    _busy.add(pid)
    try:
        title = str(product.get("title") or product.get("product_code") or f"محصول {pid}")
        last = await db.get_last_price(pid)

        # ------------------------------------------------------- استخراج
        try:
            info = await scraper.fetch(product["url"])
        except ProductUnavailable:
            await db.touch_checked(pid)
            previous = _state.get(pid, "ok")
            _state[pid] = "unavailable"
            if manual or previous != "unavailable":
                return (
                    f"📦 <b>{utils.esc(title)}</b>\n"
                    "این محصول در دیجی‌کالا ناموجود شده است 😕\n"
                    "به محض موجود شدن دوباره، قیمت را اطلاع می‌دهم."
                )
            return None
        except ScrapeError as exc:
            await db.touch_checked(pid)
            log.warning("بررسی محصول %s ناموفق (%s): %s", pid, exc.kind, exc)
            if manual:
                return ERR_BLOCKED if exc.kind == "blocked" else ERR_EXTRACT
            fails = _fail_counts.get(pid, 0) + 1
            _fail_counts[pid] = fails
            # پیام خطا فقط بار اول و هر ERROR_NOTIFY_EVERY خطای متوالی (ضد اسپم)
            if fails == 1 or fails % max(1, cfg.error_notify_every) == 0:
                return ERR_BLOCKED if exc.kind == "blocked" else ERR_EXTRACT
            return None
        except Exception:
            log.exception("خطای غیرمنتظره در بررسی محصول %s", pid)
            await db.touch_checked(pid)
            return ERR_EXTRACT if manual else None

        # ------------------------------------------------------- موفقیت
        _fail_counts.pop(pid, None)
        await db.insert_price(pid, info.price_toman)
        await db.touch_checked(pid)
        if info.title and info.title != product.get("title"):
            await db.set_title(pid, info.title)
            title = info.title
        previous_state = _state.get(pid, "ok")
        _state[pid] = "ok"
        now_utc = utils.utcnow()

        if last is None:
            return (
                f"📩 <b>{utils.esc(title)}</b>\n"
                f"💰 قیمت اولیه ثبت شد: {utils.format_price(info.price_toman)}\n"
                f"🔗 <a href=\"{utils.esc_attr(product['url'])}\">لینک محصول</a>"
            )

        old_price = int(last["price"])
        if info.price_toman != old_price:
            return utils.render_price_change(
                title=title,
                old_price=old_price,
                new_price=info.price_toman,
                checked_utc=now_utc,
                tz_name=cfg.tz_name,
                url=product["url"],
            )

        if previous_state == "unavailable":
            return (
                "✅ محصول دوباره موجود شد!\n"
                f"📱 <b>{utils.esc(title)}</b>\n"
                f"💰 قیمت فعلی: {utils.format_price(info.price_toman)}"
            )

        if manual:
            return (
                "✅ قیمتی تغییر نکرد.\n"
                f"📱 <b>{utils.esc(title)}</b>\n"
                f"💰 قیمت فعلی: {utils.format_price(info.price_toman)}\n"
                f"⏱ بازه‌ی بررسی: {utils.interval_label(int(product['interval_minutes']))}"
            )

        if cfg.notify_on_no_change:
            return (
                "ℹ️ بررسی انجام شد؛ قیمت بدون تغییر ماند.\n"
                f"📱 <b>{utils.esc(title)}</b>\n"
                f"💰 قیمت فعلی: {utils.format_price(info.price_toman)}"
            )
        return None
    finally:
        _busy.discard(pid)


# ---------------------------------------------------------------------------
# جاب دوره‌ای و ارسال
# ---------------------------------------------------------------------------


async def tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    """جاب هر دقیقه: پیدا کردن محصولات موعددار و بررسی آن‌ها."""
    cfg: Config = context.bot_data["config"]
    db: Database = context.bot_data["db"]
    scraper: BaseScraper = context.bot_data["scraper"]

    try:
        products = await db.list_active_products()
    except Exception:
        log.exception("خواندن محصولات از پایگاه داده ناموفق بود")
        return

    now = utils.utcnow()
    due = [p for p in products if is_due(p, now, cfg)]
    if not due:
        return

    log.info("بررسی دوره‌ای: %d محصول موعددار است.", len(due))
    results = await asyncio.gather(
        *(_check_one(cfg, db, scraper, p) for p in due),
        return_exceptions=True,
    )
    for product, result in zip(due, results):
        if isinstance(result, BaseException):
            log.error("خطای بررسی محصول %s: %r", product["id"], result)
            continue
        if result:
            await _send(
                db,
                context.bot,
                int(product["user_id"]),
                result,
                product_id=int(product["id"]),
            )


async def _check_one(
    cfg: Config,
    db: Database,
    scraper: BaseScraper,
    product: dict,
) -> str | None:
    try:
        return await check_product(cfg, db, scraper, product, manual=False)
    except Exception:
        log.exception("بررسی محصول %s با خطا متوقف شد", product.get("id"))
        return None


async def manual_check(context: ContextTypes.DEFAULT_TYPE, product: dict) -> str:
    """نقطه‌ی ورود «بررسی فوری قیمت» از رابط کاربری."""
    cfg: Config = context.bot_data["config"]
    db: Database = context.bot_data["db"]
    scraper: BaseScraper = context.bot_data["scraper"]
    try:
        text = await check_product(cfg, db, scraper, product, manual=True)
    except Exception:
        log.exception("بررسی فوری محصول %s با خطا مواجه شد", product.get("id"))
        text = ERR_EXTRACT
    return text or ERR_EXTRACT


async def _send(
    db: Database,
    bot,
    chat_id: int,
    text: str,
    *,
    product_id: int | None = None,
) -> None:
    """ارسال پیام HTML؛ اگر کاربر ربات را بلاک کرده باشد رصد غیرفعال می‌شود."""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Forbidden:
        if product_id is not None:
            await db.set_active(product_id, False)
            log.info(
                "کاربر %s ربات را بلاک کرده است؛ رصد محصول %s غیرفعال شد.",
                chat_id,
                product_id,
            )
    except TelegramError as exc:
        log.warning("ارسال پیام به %s ناموفق بود: %s", chat_id, exc)
