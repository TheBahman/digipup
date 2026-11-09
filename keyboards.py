"""ساخت کیبوردهای ربات Digipup (Reply برای منوی اصلی، Inline برای عملیات).

طرح داده‌ی callback_data (حداکثر ۶۴ بایت):
    menu:main                    بازگشت به منوی اصلی
    prod:actions:{pid}           پنل مدیریتی یک محصول
    act:check:{pid}              بررسی فوری قیمت
    act:interval:{pid}           نمایش انتخاب بازه‌ی بررسی
    act:toggle:{pid}             فعال/غیرفعال کردن رصد
    act:report:{pid}             نمایش گزارش قیمت
    act:delete:{pid}             نمایش تأیید حذف
    intv:{pid}:{minutes}         ذخیره‌ی بازه‌ی انتخابی
    st:toggle:{pid}              تغییر وضعیت رصد از پنل وضعیت
    del:ask:{pid} / del:yes:{pid} / del:no:{pid}   جریان حذف
"""
from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from utils import format_price_short, interval_label

# متن دکمه‌های منوی اصلی (در bot.py هم برای مسیریابی پیام استفاده می‌شود)
MENU_ADD = "➕ افزودن محصول"
MENU_LIST = "📋 لیست محصولات من"
MENU_INTERVAL = "⏱ تنظیم بازه بررسی"
MENU_STATUS = "🔔 وضعیت رصد"
MENU_DELETE = "🗑 حذف محصول"
MENU_REPORT = "📊 گزارش قیمت"
MENU_HELP = "ℹ️ راهنما"

MENU_BUTTONS = (
    MENU_ADD,
    MENU_LIST,
    MENU_INTERVAL,
    MENU_STATUS,
    MENU_DELETE,
    MENU_REPORT,
    MENU_HELP,
)
MENU_SET = set(MENU_BUTTONS)

BACK_LABEL = "↩️ بازگشت به منوی اصلی"
BACK_TO_PRODUCT_LABEL = "↩️ بازگشت به جزئیات محصول"


def _short(text: str, limit: int = 28) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------


def main_menu_kb() -> ReplyKeyboardMarkup:
    """منوی اصلی با دکمه‌های شیشه‌ای."""
    rows = [
        [KeyboardButton(MENU_ADD), KeyboardButton(MENU_LIST)],
        [KeyboardButton(MENU_INTERVAL), KeyboardButton(MENU_STATUS)],
        [KeyboardButton(MENU_DELETE), KeyboardButton(MENU_REPORT)],
        [KeyboardButton(MENU_HELP)],
    ]
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        input_field_placeholder="لینک محصول یا انتخاب از منو…",
    )


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BACK_LABEL, callback_data="menu:main")]])


def back_to_product_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(BACK_TO_PRODUCT_LABEL, callback_data=f"prod:actions:{product_id}")]]
    )


def products_list_kb(products: list[dict], action: str = "actions") -> InlineKeyboardMarkup:
    """لیست محصولات؛ با لمس هر آیتم، عمل مربوط به «action» باز می‌شود."""
    callback_prefix = {
        "actions": "prod:actions",
        "interval": "act:interval",
        "report": "act:report",
        "delete": "act:delete",
    }.get(action, "prod:actions")

    rows: list[list[InlineKeyboardButton]] = []
    for product in products:
        title = _short(str(product.get("title") or product.get("product_code") or "بدون عنوان"))
        flag = "✅" if product.get("is_active") else "⏸"
        label = f"{flag} {title}"
        price = product.get("last_price")
        if price:
            label = f"{flag} {title} — {format_price_short(int(price))}"
        rows.append(
            [InlineKeyboardButton(label, callback_data=f"{callback_prefix}:{product['id']}")]
        )
    rows.append([InlineKeyboardButton(BACK_LABEL, callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def product_actions_kb(product_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """دکمه‌های مدیریتی یک محصول."""
    toggle_label = "🔕 غیرفعال‌کردن رصد" if is_active else "🔔 فعال‌کردن رصد"
    rows = [
        [InlineKeyboardButton("🔍 بررسی فوری قیمت", callback_data=f"act:check:{product_id}")],
        [
            InlineKeyboardButton(
                "⏱ تغییر بازه‌ی بررسی", callback_data=f"act:interval:{product_id}"
            ),
            InlineKeyboardButton(toggle_label, callback_data=f"act:toggle:{product_id}"),
        ],
        [
            InlineKeyboardButton("📊 گزارش قیمت", callback_data=f"act:report:{product_id}"),
            InlineKeyboardButton("🗑 حذف محصول", callback_data=f"act:delete:{product_id}"),
        ],
        [InlineKeyboardButton(BACK_LABEL, callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(rows)


def interval_kb(
    product_id: int, current_minutes: int, choices: tuple[int, ...]
) -> InlineKeyboardMarkup:
    """انتخاب بازه‌ی بررسی؛ بازه‌ی فعلی با ✅ مشخص می‌شود."""
    rows: list[list[InlineKeyboardButton]] = []
    for minutes in choices:
        label = interval_label(minutes)
        if int(minutes) == int(current_minutes):
            label = f"✅ {label}"
        rows.append(
            [InlineKeyboardButton(label, callback_data=f"intv:{product_id}:{minutes}")]
        )
    rows.append([InlineKeyboardButton("↩️ بازگشت", callback_data=f"prod:actions:{product_id}")])
    return InlineKeyboardMarkup(rows)


def confirm_delete_kb(product_id: int) -> InlineKeyboardMarkup:
    """تأیید حذف محصول."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔥 بله، حذف کن", callback_data=f"del:yes:{product_id}"),
                InlineKeyboardButton("😌 نه، پشیمون شدم", callback_data=f"del:no:{product_id}"),
            ]
        ]
    )


def status_kb(products: list[dict]) -> InlineKeyboardMarkup:
    """پنل وضعیت رصد؛ با لمس هر محصول، فعال/غیرفعالش می‌کند."""
    rows: list[list[InlineKeyboardButton]] = []
    for product in products:
        title = _short(str(product.get("title") or product.get("product_code") or "بدون عنوان"))
        flag = "✅" if product.get("is_active") else "⏸"
        rows.append(
            [InlineKeyboardButton(f"{flag} {title}", callback_data=f"st:toggle:{product['id']}")]
        )
    rows.append([InlineKeyboardButton(BACK_LABEL, callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)
