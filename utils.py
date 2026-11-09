"""ابزارهای کمکی Digipup: اعداد فارسی، قالب‌بندی تومان، اعتبارسنجی لینک و قالب پیام‌ها.

همه‌ی خروجی‌های متنی برای ارسال با parse_mode=HTML امن شده‌اند
(محتوای کاربر/سایت هرگز بدون فرار HTML تزریق نمی‌شود).
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger("digipup.utils")

try:  # persiantools در requirements.txt هست؛ بدون آن هم ربات کار می‌کند
    from persiantools.digits import en_to_fa as _en_to_fa
except Exception:  # pragma: no cover
    def _en_to_fa(text: str) -> str:
        return str(text).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"

# ارقام فارسی (۰-۹) و عربی (٠-٩) → ارقام لاتین + حذف جداکننده‌های هزارگان
_TO_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹" + "٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TO_EN[ord("٬")] = ""  # جداکننده‌ی هزارگان عربی/فارسی
_TO_EN[ord("،")] = ""  # ویرگول فارسی

# برچسب‌های مجاز بازه‌ی بررسی
INTERVAL_LABELS: dict[int, str] = {
    15: "۱۵ دقیقه",
    30: "۳۰ دقیقه",
    60: "۱ ساعت",
    120: "۲ ساعت",
    360: "۶ ساعت",
}

# ---------------------------------------------------------------------------
# فرار HTML و ارقام
# ---------------------------------------------------------------------------


def esc(value: object) -> str:
    """فرار دادن متن کاربر/سایت برای حالت HTML تلگرام (خارج از صفات)."""
    return html.escape(str(value if value is not None else ""), quote=False)


def esc_attr(value: object) -> str:
    """فرار دادن مقدار صفات HTML مثل href."""
    return html.escape(str(value), quote=True)


def fa_digits(value: object) -> str:
    """تبدیل ارقام لاتین به فارسی."""
    return _en_to_fa(str(value))


def normalize_digits(text: str) -> str:
    """تبدیل ارقام فارسی/عربی به لاتین (برای پارس عدد)."""
    return str(text).translate(_TO_EN)


def interval_label(minutes: int) -> str:
    """برچسب خوانا برای بازه‌ی بررسی، مثل «۳۰ دقیقه» یا «۱ ساعت»."""
    return INTERVAL_LABELS.get(int(minutes), f"{fa_digits(int(minutes))} دقیقه")


# ---------------------------------------------------------------------------
# قیمت و درصد
# ---------------------------------------------------------------------------

_TOMAN_RE = re.compile(r"([\d۰-۹٠-٩,،٬.\s]+?)\s*تومان")


def parse_price_text(text: str) -> int | None:
    """«۲۱۳٬۲۱۰٬۰۰۰ تومان» را به عدد صحیح تومان تبدیل می‌کند."""
    if not text:
        return None
    match = _TOMAN_RE.search(text)
    if not match:
        return None
    cleaned = re.sub(r"[^\d]", "", normalize_digits(match.group(1)))
    if not cleaned:
        return None
    return int(cleaned)


def format_price(price: int | None) -> str:
    """قالب‌بندی خوانا و کامل قیمت به تومان؛ مثل «۲۱۳ میلیون و ۲۱۰ هزار تومان»."""
    if price is None:
        return "—"
    try:
        price = int(price)
    except (TypeError, ValueError):
        return "—"
    if price <= 0:
        return "۰ تومان"
    billion, rest = divmod(price, 1_000_000_000)
    million, rest = divmod(rest, 1_000_000)
    thousand, unit = divmod(rest, 1_000)
    parts: list[str] = []
    if billion:
        parts.append(f"{billion} میلیارد")
    if million:
        parts.append(f"{million} میلیون")
    if thousand:
        parts.append(f"{thousand} هزار")
    if unit:
        parts.append(str(unit))
    if not parts:
        text = "۰"
    elif len(parts) == 1:
        text = parts[0]
    elif len(parts) == 2:
        text = " و ".join(parts)
    else:
        text = "، ".join(parts[:-1]) + " و " + parts[-1]
    return fa_digits(text) + " تومان"


def format_price_short(price: int | None) -> str:
    """قالب‌بندی فشرده برای دکمه‌ها؛ مثل «۲۱۳٫۲ میلیون تومان»."""
    if price is None:
        return "—"
    try:
        price = int(price)
    except (TypeError, ValueError):
        return "—"
    if price <= 0:
        return "۰ تومان"
    for threshold, unit in ((1_000_000_000, "میلیارد"), (1_000_000, "میلیون"), (1_000, "هزار")):
        if price >= threshold:
            value = price / threshold
            text = f"{value:.1f}".rstrip("0").rstrip(".").replace(".", "٫")
            return fa_digits(text) + f" {unit} تومان"
    return fa_digits(str(price)) + " تومان"


def format_percent(pct: float) -> str:
    """قالب‌بندی درصد با ارقام فارسی؛ مثل «۳٪» یا «۲٫۵٪» (مقدار قدرمطلق)."""
    value = round(abs(float(pct)), 1)
    if abs(value - round(value)) < 1e-9:
        text = str(int(round(value)))
    else:
        text = f"{value:.1f}".replace(".", "٫")
    return fa_digits(text) + "٪"


# ---------------------------------------------------------------------------
# لینک دیجی‌کالا
# ---------------------------------------------------------------------------

_HOST_RE = re.compile(r"^https?://(?:www\.|m\.)?digikala\.com(?:/|\?|#|$)", re.IGNORECASE)
_DKP_RE = re.compile(r"dkp[-_](\d+)", re.IGNORECASE)


def parse_digikala_url(raw: str) -> tuple[str, str] | None:
    """لینک (یا فقط کد dkp) را اعتبارسنجی می‌کند.

    خروجی: (لینک استاندارد محصول، کد محصول) یا None اگر نامعتبر باشد.
    نمونه‌های پذیرفته‌شده:
        https://www.digikala.com/product/dkp-1234567/گوشی-...
        https://digikala.com/product/dkp-1234567
        dkp-1234567
    """
    text = (raw or "").strip().strip("<>\"' ")
    if not text:
        return None
    match = _DKP_RE.search(text)
    if not match:
        return None
    code = match.group(1)
    if text.lower().startswith(("http://", "https://")) and not _HOST_RE.match(text):
        return None
    return f"https://www.digikala.com/product/dkp-{code}/", f"dkp-{code}"


# ---------------------------------------------------------------------------
# زمان
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    """زمان فعلی به UTC (آگاه از منطقه‌ی زمانی)."""
    return datetime.now(timezone.utc)


def parse_utc(value: str | None) -> datetime | None:
    """تبدیل رشته‌ی ذخیره‌شده در پایگاه داده به datetime آگاه از UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt


def to_local(dt_utc: datetime, tz_name: str) -> datetime:
    """تبدیل UTC به منطقه‌ی زمانی محلی (پیش‌فرض: تهران)."""
    try:
        return dt_utc.astimezone(ZoneInfo(tz_name))
    except Exception:
        return dt_utc.astimezone()


def format_clock(dt_local: datetime) -> str:
    """ساعت به شکل «۱۴:۴۵»."""
    return fa_digits(dt_local.strftime("%H:%M"))


def format_date_fa(dt_local: datetime) -> str:
    """تاریخ شمسی «۱۴۰۳/۱۲/۰۵»؛ در نبود persiantools، میلادی با ارقام فارسی."""
    try:
        from persiantools.jalali import datetime as jdatetime

        jalali = jdatetime.fromgregorian(datetime=dt_local)
        return fa_digits(f"{jalali.year}/{jalali.month:02d}/{jalali.day:02d}")
    except Exception:
        return fa_digits(dt_local.strftime("%Y/%m/%d"))


# ---------------------------------------------------------------------------
# قالب پیام تغییر قیمت
# ---------------------------------------------------------------------------


def render_price_change(
    title: str,
    old_price: int,
    new_price: int,
    checked_utc: datetime,
    tz_name: str,
    url: str,
) -> str:
    """پیام استاندارد تغییر قیمت با ایموجی و اعداد فارسی.

    نمونه:
        📱 گوشی Samsung Galaxy S23 Ultra
        ⏰ ساعت ۱۴:۴۵
        📈 رشد قیمت: ۳٪
        💰 قیمت قبلی: ۲۰۷ میلیون تومان
        💵 قیمت جدید: ۲۱۳ میلیون و ۲۱۰ هزار تومان
        🔗 لینک محصول
    """
    pct = ((new_price - old_price) / old_price) * 100 if old_price > 0 else 0.0
    grew = new_price > old_price
    arrow = "📈" if grew else "📉"
    word = "رشد" if grew else "کاهش"
    clock = format_clock(to_local(checked_utc, tz_name))
    return (
        f"📱 {esc(title)}\n"
        f"⏰ ساعت {clock}\n"
        f"{arrow} {word} قیمت: {format_percent(pct)}\n"
        f"💰 قیمت قبلی: {format_price(old_price)}\n"
        f"💵 قیمت جدید: {format_price(new_price)}\n"
        f"🔗 <a href=\"{esc_attr(url)}\">لینک محصول</a>"
    )
