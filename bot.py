"""Digipup — ربات رصد قیمت دیجی‌کالا (Telegram + pyppeteer).

نقطه‌ی ورود برنامه؛ هندلرهای دستورات، منوها، کال‌بک‌ها و سیم‌کشی جاب دوره‌ای
اینجا انجام می‌شود. همه‌ی پیام‌ها با parse_mode=HTML ارسال می‌شوند و هر
محتوای کاربر/سایت قبل از تزریق با utils.esc امن می‌شود.

اجرای ربات:
    python bot.py        (بعد از تنظیم BOT_TOKEN در فایل .env)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import keyboards as kb
import scheduler
import utils
from config import Config, load_config
from db import Database
from scraper import ScrapeError, ScraperSettings, build_scraper
from utils import esc, fa_digits

log = logging.getLogger("digipup.bot")

# --------------------------------------------------------------- متن‌ها ----

WELCOME_TEXT = (
    "👋 سلام <b>{name}</b> عزیز!\n"
    "به ربات رصد قیمت دیجی‌کالا <b>Digipup</b> خوش آمدی 🐾\n\n"
    "🔗 لینک هر محصول دیجی‌کالا را بفرست تا قیمتش را برایت رصد کنم.\n"
    "⏱ بازه‌ی بررسی را می‌توانی از ۱۵ دقیقه تا ۶ ساعت تنظیم کنی.\n"
    "📈 هر وقت قیمت تغییر کند، درصد تغییر، قیمت قبلی و جدید را با جزئیات می‌گویم.\n\n"
    "از منوی زیر استفاده کن 👇"
)

ASK_LINK_TEXT = (
    "🔗 لطفاً <b>لینک محصول دیجی‌کالا</b> را بفرست.\n\n"
    "نمونه‌ی درست:\n"
    "<code>https://www.digikala.com/product/dkp-1234567/</code>\n\n"
    "می‌توانی فقط کد محصول را هم بفرستی: <code>dkp-1234567</code>\n\n"
    "برای لغو: /cancel"
)

HELP_TEXT = (
    "ℹ️ <b>راهنمای ربات Digipup</b>\n\n"
    "<b>منوی اصلی:</b>\n"
    "➕ افزودن محصول — گرفتن لینک محصول دیجی‌کالا\n"
    "📋 لیست محصولات من — دکمه‌های مدیریتی هر محصول\n"
    "⏱ تنظیم بازه بررسی — ۱۵ دقیقه، ۳۰ دقیقه، ۱ ساعت، ۲ ساعت، ۶ ساعت\n"
    "🔔 وضعیت رصد — فعال/غیرفعال کردن رصد هر محصول\n"
    "🗑 حذف محصول — حذف با تأیید\n"
    "📊 گزارش قیمت — کمینه، بیشینه، میانگین و بررسی‌های اخیر\n"
    "ℹ️ راهنما — همین پیام\n\n"
    "<b>دکمه‌های مدیریتی هر محصول:</b>\n"
    "🔍 بررسی فوری قیمت — چک دستی بدون انتظار برای بازه\n"
    "⏱ تغییر بازه‌ی بررسی | 🔔/🔕 فعال/غیرفعال کردن رصد\n"
    "📊 گزارش قیمت | 🗑 حذف محصول\n\n"
    "<b>نکته‌ها:</b>\n"
    "• می‌توانی لینک محصول را مستقیم در چت بفرستی (بدون منو).\n"
    "• حداقل بازه‌ی بررسی ۱۵ دقیقه است و بین بررسی‌ها تأخیر تصادفی کوچکی "
    "(jitter) اعمال می‌شود تا به سایت فشار نیاید.\n"
    "• اگر قیمت تغییر نکند پیامی نمی‌فرستم؛ فقط تغییرات اطلاع داده می‌شوند.\n"
    "• دستور /cancel هر عملیات در جریان را لغو می‌کند.\n\n"
    "<b>محدودیت‌ها:</b>\n"
    "• ساختار صفحه‌ی دیجی‌کالا ممکن است تغییر کند؛ در آن صورت استخراج قیمت "
    "موقتاً ناموفق می‌شود و پیام خطا می‌گیری.\n"
    "• در صورت بلاک شدن یا پاسخ نامعتبر سایت، بررسی بعدی طبق زمان‌بندی انجام می‌شود.\n"
    "• استفاده از ربات باید مطابق قوانین دیجی‌کالا و با نرخ درخواست معقول باشد."
)

MAIN_MENU_TEXT = "🏠 <b>منوی اصلی</b>\nاز دکمه‌های زیر استفاده کن یا لینک محصول را بفرست:"

ERR_BAD_LINK = (
    "❌ لطفاً یک لینک معتبر محصول دیجی‌کالا بفرست.\n"
    "نمونه‌ی درست:\n<code>https://www.digikala.com/product/dkp-1234567/</code>"
)
ERR_DUPLICATE = (
    "⚠️ این محصول قبلاً برای شما ثبت شده است.\n"
    "از «📋 لیست محصولات من» می‌توانی مدیریتش کنی."
)
ERR_NOT_FOUND = "🤷 این محصول پیدا نشد یا به حساب شما تعلق ندارد."

# تیتر پنل‌های لیست‌محور
_PANEL_HEADERS = {
    "actions": "📋 <b>لیست محصولات شما</b>\nروی هر محصول بزنید تا دکمه‌های مدیریتی باز شود:",
    "interval": "⏱ <b>تنظیم بازه‌ی بررسی</b>\nبرای کدام محصول؟",
    "report": "📊 <b>گزارش قیمت</b>\nگزارش کدام محصول را می‌خواهی؟",
    "delete": "🗑 <b>حذف محصول</b>\nکدام محصول حذف شود؟",
}


# ------------------------------------------------------------- لاگ‌ها ----


class _TokenScrubFilter(logging.Filter):
    """هر جا توکن در متن لاگ ظاهر شود، ماسک می‌کند (حتی در خطاهای ناخواسته)."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            if self._token and self._token in message:
                record.msg = message.replace(self._token, "***TOKEN***")
                record.args = ()
        except Exception:
            pass
        return True


def setup_logging(level: str, token: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    handler.addFilter(_TokenScrubFilter(token))
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers = [handler]


# ------------------------------------------------- ابزارهای داخلی ----


async def _owned_product(db: Database, product_id: int, user_id: int) -> dict | None:
    """محصول را می‌خواند و بررسی می‌کند به کاربر فعلی تعلق دارد."""
    product = await db.get_product(product_id)
    if product is None or int(product["user_id"]) != int(user_id):
        return None
    return product


def _next_check_text(product: dict, cfg: Config) -> str:
    """توضیح خوانای زمان بررسی بعدی."""
    if not product.get("is_active"):
        return "⏸ رصد این محصول غیرفعال است."
    last = utils.parse_utc(product.get("last_checked_at"))
    if last is None:
        return "🔎 بررسی بعدی: در اولین فرصت (کمتر از یک دقیقه‌ی دیگر)"
    interval = timedelta(
        minutes=max(cfg.min_interval_minutes, int(product["interval_minutes"]))
    )
    remaining = (last + interval - utils.utcnow()).total_seconds() / 60
    if remaining <= 0:
        return "🔎 بررسی بعدی: همین حالا"
    return f"🔎 بررسی بعدی: حدوداً {fa_digits(int(remaining) + 1)} دقیقه دیگر"


async def _actions_panel(db: Database, cfg: Config, product: dict) -> tuple[str, object]:
    """متن + کیبورد پنل مدیریتی یک محصول."""
    product_id = int(product["id"])
    title = esc(product.get("title") or product["product_code"])
    lines = [
        f"📦 <b>{title}</b>",
        f"🆔 کد محصول: <code>{esc(product['product_code'])}</code>",
    ]
    last = await db.get_last_price(product_id)
    if last:
        checked = utils.parse_utc(last["checked_at"])
        clock = utils.format_clock(utils.to_local(checked, cfg.tz_name)) if checked else "—"
        lines.append(
            f"💰 آخرین قیمت: {utils.format_price(int(last['price']))} (ساعت {clock})"
        )
    else:
        lines.append("💰 هنوز قیمتی ثبت نشده است.")
    lines.append(f"⏱ بازه‌ی بررسی: {utils.interval_label(int(product['interval_minutes']))}")
    lines.append("🔔 وضعیت رصد: فعال ✅" if product["is_active"] else "🔕 وضعیت رصد: غیرفعال ⏸")
    lines.append(_next_check_text(product, cfg))
    return "\n".join(lines), kb.product_actions_kb(product_id, bool(product["is_active"]))


async def _products_panel(
    db: Database, user_id: int, action: str
) -> tuple[str, object]:
    """پنل لیست محصولات برای چهار منظور: مدیریت/بازه/گزارش/حذف."""
    products = await db.list_products(user_id)
    if not products:
        return (
            "🌱 هنوز محصولی ثبت نکرده‌اید.\n"
            "با دکمه‌ی «➕ افزودن محصول» یا ارسال مستقیم لینک یک محصول دیجی‌کالا شروع کن.",
            kb.back_kb(),
        )
    shown = products[:40]
    for product in shown:
        last = await db.get_last_price(int(product["id"]))
        product["last_price"] = int(last["price"]) if last else None
    text = _PANEL_HEADERS.get(action, _PANEL_HEADERS["actions"])
    if len(products) > len(shown):
        text += f"\n\n({fa_digits(len(products) - len(shown))} محصول دیگر نمایش داده نشد)"
    return text, kb.products_list_kb(shown, action=action)


async def _status_panel(db: Database, cfg: Config, user_id: int) -> tuple[str, object]:
    """پنل وضعیت رصد؛ هر دکمه فعال/غیرفعال می‌کند."""
    products = await db.list_products(user_id)
    if not products:
        return "🌱 محصولی برای نمایش وضعیت وجود ندارد.", kb.back_kb()
    shown = products[:40]
    lines = ["🔔 <b>وضعیت رصد محصولات</b>", "(با لمس هر محصول، رصدش فعال/غیرفعال می‌شود)", ""]
    for product in shown:
        flag = "✅" if product["is_active"] else "⏸"
        title = esc(product.get("title") or product["product_code"])
        last = await db.get_last_price(int(product["id"]))
        price = utils.format_price_short(int(last["price"])) if last else "—"
        interval = utils.interval_label(int(product["interval_minutes"]))
        lines.append(f"{flag} <b>{title}</b> — 💰 {price} | ⏱ {interval}")
    if len(products) > len(shown):
        lines.append(f"\n({fa_digits(len(products) - len(shown))} محصول دیگر نمایش داده نشد)")
    return "\n".join(lines), kb.status_kb(shown)


async def _report_text(db: Database, cfg: Config, product: dict) -> str:
    """گزارش کامل قیمت یک محصول."""
    product_id = int(product["id"])
    title = esc(product.get("title") or product["product_code"])
    lines = ["📊 <b>گزارش قیمت</b>", f"📱 {title}", ""]
    stats = await db.get_price_stats(product_id)
    last = await db.get_last_price(product_id)
    if not stats or not last:
        lines.append("هنوز قیمتی برای این محصول ثبت نشده است.\nبا «🔍 بررسی فوری قیمت» شروع کن.")
        return "\n".join(lines)

    first = await db.get_first_price(product_id)
    recent = await db.get_recent_history(product_id, limit=7)

    if first and int(first["price"]) != int(last["price"]):
        pct = ((int(last["price"]) - int(first["price"])) / int(first["price"])) * 100
        direction = "رشد 📈" if pct > 0 else "کاهش 📉"
        lines.append(f"🔢 نسبت به شروع رصد: {utils.format_percent(pct)} {direction}")

    lines += [
        f"🧮 تعداد بررسی‌ها: {fa_digits(stats['checks'])}",
        f"⬇️ کمترین قیمت: {utils.format_price(int(stats['min_price']))}",
        f"⬆️ بیشترین قیمت: {utils.format_price(int(stats['max_price']))}",
        f"⚖️ میانگین قیمت: {utils.format_price(int(round(float(stats['avg_price']))))}",
        "",
        "🕘 بررسی‌های اخیر:",
    ]
    for entry in recent:
        checked = utils.parse_utc(entry["checked_at"])
        clock = utils.format_clock(utils.to_local(checked, cfg.tz_name)) if checked else "—"
        lines.append(f"　• ساعت {clock} — {utils.format_price(int(entry['price']))}")
    return "\n".join(lines)


# ------------------------------------------------------------- ارسال ----


async def _edit(update: Update, text: str, reply_markup) -> None:
    """ویرایش پیام اینلاین؛ خطای «پیام تغییر نکرده» نادیده گرفته می‌شود."""
    message = update.effective_message
    if message is None:
        return
    try:
        await message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


async def _notify_missing(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    await context.bot.send_message(chat_id, ERR_NOT_FOUND, parse_mode=ParseMode.HTML)


# ------------------------------------------------------ دستورات ----


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start: ثبت کاربر + پیام خوش‌آمد + منوی اصلی."""
    if update.message is None or update.effective_user is None:
        return
    db: Database = context.bot_data["db"]
    await db.upsert_user(update.effective_user.id, update.effective_user.username)
    context.user_data["awaiting"] = None
    name = esc(update.effective_user.first_name or "دوست من")
    await update.message.reply_text(
        WELCOME_TEXT.format(name=name),
        parse_mode=ParseMode.HTML,
        reply_markup=kb.main_menu_kb(),
        disable_web_page_preview=True,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        HELP_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=kb.main_menu_kb(),
        disable_web_page_preview=True,
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    context.user_data["awaiting"] = None
    await update.message.reply_text(
        "🚫 عملیات لغو شد.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.main_menu_kb(),
    )


# --------------------------------------------- افزودن محصول ----


async def handle_add_link(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """اعتبارسنجی لینک، جلوگیری از ثبت تکراری، استخراج اولیه و ثبت محصول."""
    db: Database = context.bot_data["db"]
    cfg: Config = context.bot_data["config"]
    scraper = context.bot_data["scraper"]
    user = update.effective_user

    parsed = utils.parse_digikala_url(text)
    if parsed is None:
        context.user_data["awaiting"] = None
        await update.message.reply_text(ERR_BAD_LINK, parse_mode=ParseMode.HTML)
        return

    url, code = parsed
    context.user_data["awaiting"] = None

    existing = await db.get_product_by_code(user.id, code)
    if existing is not None:
        await update.message.reply_text(
            ERR_DUPLICATE,
            parse_mode=ParseMode.HTML,
            reply_markup=kb.main_menu_kb(),
        )
        return

    waiting = await update.message.reply_text("⏳ در حال دریافت اطلاعات محصول… چند لحظه صبر کن.")
    info = None
    try:
        # استخراج اولیه با سقف زمانی مشخص تا کاربر زیاد منتظر نماند
        info = await asyncio.wait_for(
            scraper.fetch(url), timeout=cfg.page_timeout_seconds + 15
        )
    except asyncio.TimeoutError:
        log.warning("استخراج اولیه برای %s تایم‌اوت شد.", code)
    except ScrapeError as exc:
        log.warning("استخراج اولیه برای %s ناموفق بود (%s): %s", code, exc.kind, exc)
    except Exception:
        log.exception("خطای غیرمنتظره در استخراج اولیه‌ی %s", code)

    product_id = await db.add_product(
        user.id, code, url, info.title if info else None, cfg.default_interval_minutes
    )
    if product_id is None:  # ثبت هم‌زمان توسط پیام دیگری
        await waiting.edit_text(ERR_DUPLICATE, parse_mode=ParseMode.HTML)
        return

    if info is not None:
        await db.insert_price(product_id, info.price_toman)
        await db.touch_checked(product_id)
        saved = await db.get_product(product_id)
        title = esc((saved or {}).get("title") or code)
        reply_text = (
            "✅ محصول با موفقیت ثبت شد!\n\n"
            f"📱 <b>{title}</b>\n"
            f"💰 قیمت فعلی: {utils.format_price(info.price_toman)}\n"
            f"⏱ بازه‌ی بررسی: {utils.interval_label(cfg.default_interval_minutes)}\n\n"
            "هر وقت قیمتش تغییر کند، خبرت می‌کنم 🐾"
        )
    else:
        reply_text = (
            "✅ محصول ثبت شد، اما ⚠️ فعلاً نتوانستم قیمت را بخوانم.\n"
            "در اولین بررسی خودکار (حداکثر یک دقیقه‌ی دیگر) نتیجه را اطلاع می‌دهم.\n"
            f"⏱ بازه‌ی بررسی: {utils.interval_label(cfg.default_interval_minutes)}"
        )

    await waiting.edit_text(
        reply_text,
        parse_mode=ParseMode.HTML,
        reply_markup=kb.product_actions_kb(product_id, is_active=True),
        disable_web_page_preview=True,
    )


# --------------------------------------------------------- پیام متنی ----


async def _handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    db: Database = context.bot_data["db"]
    cfg: Config = context.bot_data["config"]
    user_id = update.effective_user.id

    if text == kb.MENU_ADD:
        context.user_data["awaiting"] = "link"
        await update.message.reply_text(ASK_LINK_TEXT, parse_mode=ParseMode.HTML)
        return

    context.user_data["awaiting"] = None

    if text == kb.MENU_LIST:
        panel_text, markup = await _products_panel(db, user_id, "actions")
    elif text == kb.MENU_INTERVAL:
        panel_text, markup = await _products_panel(db, user_id, "interval")
    elif text == kb.MENU_STATUS:
        panel_text, markup = await _status_panel(db, cfg, user_id)
    elif text == kb.MENU_DELETE:
        panel_text, markup = await _products_panel(db, user_id, "delete")
    elif text == kb.MENU_REPORT:
        panel_text, markup = await _products_panel(db, user_id, "report")
    elif text == kb.MENU_HELP:
        await update.message.reply_text(
            HELP_TEXT,
            parse_mode=ParseMode.HTML,
            reply_markup=kb.main_menu_kb(),
            disable_web_page_preview=True,
        )
        return
    else:  # نباید رخ دهد
        return

    await update.message.reply_text(
        panel_text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مسیریابی پیام‌های متنی: منو، لینک مستقیم یا ورودی در انتظار لینک."""
    if update.message is None or update.effective_user is None:
        return
    db: Database = context.bot_data["db"]
    text = (update.message.text or "").strip()
    await db.upsert_user(update.effective_user.id, update.effective_user.username)

    if text in kb.MENU_SET:
        await _handle_menu(update, context, text)
        return

    if utils.parse_digikala_url(text) or context.user_data.get("awaiting") == "link":
        await handle_add_link(update, context, text)
        return

    await update.message.reply_text(
        "🙂 متوجه پیامت نشدم.\nلینک یک محصول دیجی‌کالا بفرست یا از منوی زیر استفاده کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.main_menu_kb(),
    )


# ---------------------------------------------------------- کال‌بک‌ها ----


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مسیریابی همه‌ی دکمه‌های اینلاین."""
    if update.callback_query is None or update.effective_user is None:
        return
    query = update.callback_query
    data = query.data or ""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id if update.effective_chat else user_id
    db: Database = context.bot_data["db"]
    cfg: Config = context.bot_data["config"]

    try:
        await query.answer()
    except TelegramError:
        pass

    parts = data.split(":")
    try:
        if data == "noop":
            return

        if parts[0] == "menu":
            await context.bot.send_message(
                chat_id,
                MAIN_MENU_TEXT,
                parse_mode=ParseMode.HTML,
                reply_markup=kb.main_menu_kb(),
            )
            return

        # پنل مدیریتی محصول
        if parts[0] == "prod" and len(parts) == 3 and parts[1] == "actions":
            product = await _owned_product(db, int(parts[2]), user_id)
            if product is None:
                await _notify_missing(context, chat_id)
                return
            panel_text, markup = await _actions_panel(db, cfg, product)
            await _edit(update, panel_text, markup)
            return

        # عملیات‌های محصول
        if parts[0] == "act" and len(parts) == 3:
            action = parts[1]
            product = await _owned_product(db, int(parts[2]), user_id)
            if product is None:
                await _notify_missing(context, chat_id)
                return
            product_id = int(product["id"])

            if action == "check":
                await context.bot.send_message(
                    chat_id, "⏳ <b>بررسی فوری در جریان است…</b>", parse_mode=ParseMode.HTML
                )
                result_text = await scheduler.manual_check(context, product)
                await context.bot.send_message(
                    chat_id,
                    result_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                return

            if action == "interval":
                title = esc(product.get("title") or product["product_code"])
                await _edit(
                    update,
                    f"⏱ <b>بازه‌ی بررسی برای «{title}»</b>\nبازه‌ی دلخواه را انتخاب کن:",
                    kb.interval_kb(product_id, int(product["interval_minutes"]), cfg.interval_choices),
                )
                return

            if action == "toggle":
                new_state = not bool(product["is_active"])
                await db.set_active(product_id, new_state)
                product["is_active"] = 1 if new_state else 0
                panel_text, markup = await _actions_panel(db, cfg, product)
                await _edit(update, panel_text, markup)
                return

            if action == "report":
                await _edit(update, await _report_text(db, cfg, product), kb.back_to_product_kb(product_id))
                return

            if action == "delete":
                title = esc(product.get("title") or product["product_code"])
                await _edit(
                    update,
                    (
                        "🗑 <b>حذف محصول</b>\n\n"
                        f"«{title}» و کل تاریخچه‌ی قیمتش پاک خواهد شد.\n"
                        "مطمئن هستی؟"
                    ),
                    kb.confirm_delete_kb(product_id),
                )
                return

        # تغییر وضعیت از پنل وضعیت رصد
        if parts[0] == "st" and len(parts) == 3 and parts[1] == "toggle":
            product = await _owned_product(db, int(parts[2]), user_id)
            if product is None:
                await _notify_missing(context, chat_id)
                return
            await db.set_active(int(product["id"]), not bool(product["is_active"]))
            panel_text, markup = await _status_panel(db, cfg, user_id)
            await _edit(update, panel_text, markup)
            return

        # ذخیره‌ی بازه‌ی بررسی
        if parts[0] == "intv" and len(parts) == 3:
            product_id = int(parts[1])
            minutes = int(parts[2])
            product = await _owned_product(db, product_id, user_id)
            if product is None:
                await _notify_missing(context, chat_id)
                return
            if minutes not in cfg.interval_choices or minutes < cfg.min_interval_minutes:
                await _edit(update, "❌ این بازه مجاز نیست.", kb.back_to_product_kb(product_id))
                return
            await db.set_interval(product_id, minutes)
            title = esc(product.get("title") or product["product_code"])
            await _edit(
                update,
                f"⏱ بازه‌ی بررسی «{utils.interval_label(minutes)}» برای «{title}» ذخیره شد.",
                kb.back_to_product_kb(product_id),
            )
            return

        # جریان حذف
        if parts[0] == "del" and len(parts) == 3:
            product = await _owned_product(db, int(parts[2]), user_id)
            if product is None:
                await _notify_missing(context, chat_id)
                return
            title = esc(product.get("title") or product["product_code"])
            if parts[1] == "yes":
                await db.delete_product(int(product["id"]))
                await _edit(update, f"🗑 محصول «{title}» و تاریخچه‌ی قیمتش حذف شد.", kb.back_kb())
            else:
                panel_text, markup = await _actions_panel(db, cfg, product)
                await _edit(update, panel_text, markup)
            return

        # داده‌ی ناشناخته
        await _edit(update, "🤔 این دکمه شناخته نشد؛ از منوی اصلی ادامه بده.", kb.back_kb())

    except ValueError:
        await _edit(update, "🤔 پارامتر دکمه نامعتبر بود؛ از منوی اصلی ادامه بده.", kb.back_kb())
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        log.warning("BadRequest در کال‌بک «%s»: %s", data, exc)
    except TelegramError as exc:
        log.warning("خطای تلگرام در کال‌بک «%s»: %s", data, exc)


# ----------------------------------------------------- خطاهای کلی ----


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لاگ خطا + پیام عمومی به کاربر (بدون افشای جزئیات فنی)."""
    log.error("استثنای مدیریت‌نشده", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                update.effective_chat.id,
                "😕 خطای غیرمنتظره‌ای پیش آمد. لطفاً دوباره تلاش کن.",
            )
        except TelegramError:
            pass


# ------------------------------------------------- راه‌اندازی برنامه ----


async def _post_init(application: Application) -> None:
    await application.bot_data["db"].connect()
    await application.bot.set_my_commands(
        [
            BotCommand("start", "شروع و نمایش منوی اصلی"),
            BotCommand("help", "راهنمای ربات"),
            BotCommand("cancel", "لغو عملیات در جریان"),
        ]
    )
    log.info("Digipup آماده است؛ polling شروع می‌شود.")


async def _post_shutdown(application: Application) -> None:
    scraper = application.bot_data.get("scraper")
    db = application.bot_data.get("db")
    if scraper is not None:
        try:
            await scraper.close()
        except Exception:
            log.exception("بستن موتور استخراج با خطا مواجه شد")
    if db is not None:
        try:
            await db.close()
        except Exception:
            log.exception("بستن پایگاه داده با خطا مواجه شد")


def main() -> None:
    cfg = load_config()
    setup_logging(cfg.log_level, cfg.bot_token)

    db = Database(cfg.db_path)
    scraper = build_scraper(
        cfg.scrape_backend,
        ScraperSettings(
            page_timeout_seconds=float(cfg.page_timeout_seconds),
            retry_attempts=cfg.retry_attempts,
            retry_backoff_seconds=cfg.retry_backoff_seconds,
            max_concurrent_pages=cfg.max_concurrent_pages,
            user_agent=cfg.user_agent,
            headless=cfg.headless,
            chrome_executable_path=cfg.chrome_executable_path,
            price_unit=cfg.price_unit,
        ),
    )

    application = (
        ApplicationBuilder()
        .token(cfg.bot_token)
        .concurrent_updates(True)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.bot_data["config"] = cfg
    application.bot_data["db"] = db
    application.bot_data["scraper"] = scraper

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("cancel", cmd_cancel))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_error_handler(on_error)

    if application.job_queue is None:
        raise SystemExit(
            "python-telegram-bot با اکسترا [job-queue] نصب نشده است؛ "
            "دستور `pip install -r requirements.txt` را اجرا کنید."
        )
    application.job_queue.run_repeating(
        scheduler.tick,
        interval=cfg.scheduler_tick_seconds,
        first=10,
        name="price-checker",
        job_kwargs={"max_instances": 2},
    )

    log.info(
        "Digipup راه‌اندازی شد (backend=%s, db=%s, tz=%s).",
        cfg.scrape_backend,
        cfg.db_path,
        cfg.tz_name,
    )
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
