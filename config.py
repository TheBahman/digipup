"""بارگذاری تنظیمات ربات Digipup از فایل .env.

هیچ مقدار حساسی در کد hardcode نمی‌شود؛ BOT_TOKEN حتماً باید در .env قرار بگیرد.
همه‌ی مقادیر اختیاری‌اند و مقدار پیش‌فرض منطقی دارند.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# فایل .env کنار پروژه خوانده می‌شود (اگر وجود داشته باشد)
load_dotenv()

TRUTHY = {"1", "true", "yes", "on", "y"}

VALID_BACKENDS = ("pyppeteer", "dummy")
VALID_PRICE_UNITS = ("auto", "toman", "rrial")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _get_str(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else default


def _get_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = _get_str(name)
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


def _get_float(name: str, default: float, minimum: float | None = None) -> float:
    raw = _get_str(name)
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


def _get_bool(name: str, default: bool) -> bool:
    raw = _get_str(name).lower()
    if not raw:
        return default
    return raw in TRUTHY


@dataclass(frozen=True)
class Config:
    """تنظیمات کامل ربات."""

    bot_token: str
    db_path: str
    tz_name: str
    log_level: str

    # موتور استخراج قیمت
    scrape_backend: str
    chrome_executable_path: str
    headless: bool
    page_timeout_seconds: int
    max_concurrent_pages: int
    retry_attempts: int
    retry_backoff_seconds: float
    user_agent: str
    price_unit: str

    # زمان‌بندی و اعلان‌ها
    default_interval_minutes: int
    min_interval_minutes: int
    interval_choices: tuple[int, ...]
    jitter_seconds: int
    scheduler_tick_seconds: int
    notify_on_no_change: bool
    error_notify_every: int


def load_config() -> Config:
    """تنظیمات را از متغیرهای محیطی/.env می‌خواند و اعتبارسنجی می‌کند."""
    bot_token = _get_str("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError(
            "BOT_TOKEN تنظیم نشده است. فایل .env.example را به .env کپی کنید و "
            "توکن ربات را که از @BotFather گرفته‌اید داخل آن بگذارید."
        )

    scrape_backend = _get_str("SCRAPE_BACKEND", "pyppeteer").lower()
    if scrape_backend not in VALID_BACKENDS:
        raise RuntimeError(
            f"SCRAPE_BACKEND باید یکی از {VALID_BACKENDS} باشد (مقدار فعلی: {scrape_backend})."
        )

    price_unit = _get_str("PRICE_UNIT", "auto").lower()
    if price_unit not in VALID_PRICE_UNITS:
        raise RuntimeError(
            f"PRICE_UNIT باید یکی از {VALID_PRICE_UNITS} باشد (مقدار فعلی: {price_unit})."
        )

    min_interval = _get_int("MIN_INTERVAL_MINUTES", 15, minimum=1)
    default_interval = _get_int("DEFAULT_INTERVAL_MINUTES", 30, minimum=min_interval)

    choices_raw = _get_str("INTERVAL_CHOICES", "15,30,60,120,360")
    choices: set[int] = set()
    for chunk in choices_raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            minutes = int(chunk)
        except ValueError:
            continue
        if minutes >= min_interval:
            choices.add(minutes)
    choices.add(default_interval)
    if not choices:
        choices = {min_interval}

    return Config(
        bot_token=bot_token,
        db_path=_get_str("DB_PATH", "digipup.db") or "digipup.db",
        tz_name=_get_str("TZ_NAME", "Asia/Tehran") or "Asia/Tehran",
        log_level=_get_str("LOG_LEVEL", "INFO").upper(),
        scrape_backend=scrape_backend,
        chrome_executable_path=_get_str("CHROME_EXECUTABLE_PATH"),
        headless=_get_bool("HEADLESS", True),
        page_timeout_seconds=_get_int("PAGE_TIMEOUT_SECONDS", 45, minimum=5),
        max_concurrent_pages=_get_int("MAX_CONCURRENT_PAGES", 2, minimum=1),
        retry_attempts=_get_int("RETRY_ATTEMPTS", 2, minimum=1),
        retry_backoff_seconds=_get_float("RETRY_BACKOFF_SECONDS", 3.0, minimum=0.0),
        user_agent=_get_str("USER_AGENT", DEFAULT_USER_AGENT) or DEFAULT_USER_AGENT,
        price_unit=price_unit,
        default_interval_minutes=default_interval,
        min_interval_minutes=min_interval,
        interval_choices=tuple(sorted(choices)),
        jitter_seconds=_get_int("JITTER_SECONDS", 30, minimum=0),
        scheduler_tick_seconds=_get_int("SCHEDULER_TICK_SECONDS", 60, minimum=15),
        notify_on_no_change=_get_bool("NOTIFY_ON_NO_CHANGE", False),
        error_notify_every=_get_int("ERROR_NOTIFY_EVERY", 6, minimum=1),
    )
