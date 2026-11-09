"""لایه‌ی استخراج قیمت دیجی‌کالا — جدا و قابل تعویض.

پیش‌فرض موتور: pyppeteer (پورت پایتونی Puppeteer).

ترتیب استخراج قیمت و عنوان:
    ۱) JSON-LD          (schema.org/Product → offers.price / priceCurrency)
    ۲) __NEXT_DATA__    (فیلد selling_price واریانت محصول)
    ۳) سلکتورهای CSS    (متن «عدد + تومان» داخل عناصر قیمت)
    ۴) متای صفحه        (فقط برای عنوان؛ og:title و مشابه)

برای تعویض موتور (مثلاً Playwright یا سرویس Node.js/Puppeteer) فقط کافی است
یک زیرکلاس از BaseScraper بنویسید و در BUILDERS ثبت کنید؛ بقیه‌ی پروژه تغییری
نمی‌کند. راهنمای کامل در README، بخش «تعویض لایه‌ی استخراج».

اصول رفتار محترمانه با سایت:
- User-Agent معمولی مرورگر (بدون هدر جعلی غیرمعمول)
- تایم‌اوت مشخص، تعداد تلاش محدود و فاصله‌ی backoff بین تلاش‌ها
- محدودیت تعداد صفحه‌ی هم‌زمان (semaphore)
- هیچ تلاشی برای دور زدن کپچا/محافظت‌ها انجام نمی‌شود؛ در صورت بلاک، خطای
  قابل فهم به کاربر اعلام می‌شود.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Optional

from bs4 import BeautifulSoup

import utils

log = logging.getLogger("digipup.scraper")


# ---------------------------------------------------------------------------
# خطاها
# ---------------------------------------------------------------------------


class ScrapeError(Exception):
    """خطای پایه‌ی استخراج؛ kind نوع خطا را مشخص می‌کند."""

    kind = "parse"  # timeout | blocked | unavailable | parse | browser


class ScrapeTimeout(ScrapeError):
    kind = "timeout"


class SiteBlocked(ScrapeError):
    kind = "blocked"


class ProductUnavailable(ScrapeError):
    kind = "unavailable"


class PriceNotFound(ScrapeError):
    kind = "parse"


class BrowserUnavailable(ScrapeError):
    kind = "browser"


@dataclass(frozen=True)
class ScraperSettings:
    """تنظیمات موتور استخراج؛ در bot.py از Config ساخته و تزریق می‌شود."""

    page_timeout_seconds: float = 45.0
    retry_attempts: int = 2
    retry_backoff_seconds: float = 3.0
    max_concurrent_pages: int = 2
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    accept_language: str = "fa-IR,fa;q=0.9,en-US;q=0.8"
    headless: bool = True
    chrome_executable_path: str = ""
    price_unit: str = "auto"  # auto | toman | rrial
    viewport_width: int = 1366
    viewport_height: int = 850


@dataclass
class ProductInfo:
    """نتیجه‌ی موفق استخراج."""

    title: Optional[str]
    price_toman: int
    source: str  # json_ld | next_data | css | dummy


# ---------------------------------------------------------------------------
# سلکتورهای قابل تنظیم
# ---------------------------------------------------------------------------

SELECTORS: dict[str, list[str]] = {
    # قیمت نمایش‌داده‌شده‌ی صفحه (به تومان)؛ به ترتیب اولویت امتحان می‌شوند.
    # برای افزودن سلکتور جدید، رشته‌اش را به ابتدای همین لیست اضافه کنید.
    "price": [
        '[data-testid="price-current"]',
        '[data-testid="price-no-discount"]',
        '[data-testid="price-final"]',
        '[data-testid="price"]',
        ".price-inside-text",
    ],
    # عنوان محصول؛ به ترتیب اولویت.
    "title": [
        '[data-testid="product-title"]',
        "h1[data-testid='product-title']",
        'meta[property="og:title"]',
        'meta[name="twitter:title"]',
        "title",
    ],
    # اسکریپت‌های داده‌ی ساختاریافته.
    "json_ld": ['script[type="application/ld+json"]'],
    "next_data": ["script#__NEXT_DATA__"],
}

# نشانه‌های ناموجود بودن / بلاک شدن (فقط وقتی قیمت پیدا نشد بررسی می‌شوند)
UNAVAILABLE_MARKERS: tuple[str, ...] = (
    "ناموجود",
    "این کالا در حال حاضر موجود نمی‌باشد",
    "موجود نمی باشد",
    "تمام شد",
)
BLOCK_MARKERS: tuple[str, ...] = (
    "captcha",
    "کپچا",
    "access denied",
    "forbidden",
    "unusual traffic",
    "are you a human",
)


# ---------------------------------------------------------------------------
# توابع خالص تحلیل HTML (بدون مرورگر؛ قابل تست)
# ---------------------------------------------------------------------------


def _soup(html_text: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html_text, "lxml")
    except Exception:  # اگر lxml در دسترس نبود
        return BeautifulSoup(html_text, "html.parser")


def _json_ld_blocks(soup: BeautifulSoup) -> list:
    blocks: list = []
    for tag in soup.select(SELECTORS["json_ld"][0]):
        raw = (tag.string or tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
    return blocks


def _iter_product_nodes(nodes: list) -> Iterator[dict]:
    """پیمایش درخت JSON و بازگرداندن گره‌های @type=Product."""
    stack = list(nodes)
    while stack:
        current = stack.pop()
        if isinstance(current, list):
            stack.extend(current)
        elif isinstance(current, dict):
            types = current.get("@type")
            if isinstance(types, str):
                types = [types]
            if isinstance(types, list) and any(str(t).lower() == "product" for t in types):
                yield current
            stack.extend(v for v in current.values() if isinstance(v, (dict, list)))


def to_toman(raw: int, source: str, currency: str | None, policy: str) -> int:
    """تبدیل مقدار خام به تومان بر اساس سیاست PRICE_UNIT.

    - toman: هیچ تبدیلی انجام نمی‌شود.
    - rrial: همیشه بر ۱۰ تقسیم می‌شود (ریال → تومان).
    - auto : اگر priceCurrency صریحاً IRR/RIAL باشد تقسیم بر ۱۰، اگر IRT/TOMAN
             باشد بدون تغییر؛ در نبود ارز، داده‌های ساختاریافته‌ی دیجی‌کالا
             (json_ld و next_data) به‌طور سنتی ریال هستند و تقسیم می‌شوند، ولی
             متن CSS چون پسوند «تومان» دارد دست‌نخورده می‌ماند.
    """
    if policy == "toman":
        return raw
    if policy == "rrial":
        return raw // 10
    if currency:
        currency = currency.upper()
        if currency in {"IRR", "RIAL"}:
            return raw // 10
        if currency in {"IRT", "TOMAN"}:
            return raw
    if source in {"json_ld", "next_data"}:
        return raw // 10
    return raw


def price_from_json_ld(
    soup: BeautifulSoup, policy: str
) -> tuple[int, Optional[str]] | None:
    for product in _iter_product_nodes(_json_ld_blocks(soup)):
        offers = product.get("offers")
        if isinstance(offers, dict):
            offer_list = [offers]
        elif isinstance(offers, list):
            offer_list = [o for o in offers if isinstance(o, dict)]
        else:
            offer_list = []
        for offer in offer_list:
            raw_price = offer.get("price", offer.get("lowPrice"))
            if raw_price in (None, ""):
                continue
            try:
                price_int = int(
                    round(float(utils.normalize_digits(str(raw_price)).replace(",", "")))
                )
            except (TypeError, ValueError):
                continue
            if price_int <= 0:
                continue
            currency = str(offer.get("priceCurrency") or "").strip().upper() or None
            name = product.get("name")
            return (
                to_toman(price_int, "json_ld", currency, policy),
                name if isinstance(name, str) else None,
            )
    return None


def price_from_next_data(
    soup: BeautifulSoup, policy: str
) -> tuple[int, Optional[str]] | None:
    tag = soup.select_one(SELECTORS["next_data"][0])
    if tag is None:
        return None
    raw = (tag.string or tag.get_text() or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    found: dict = {}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            price = node.get("selling_price")
            if isinstance(price, (int, float)) and price > 0 and "price" not in found:
                found["price"] = int(price)
            if "title" not in found:
                # عنوان در دیکتری جدا از قیمت است؛ فقط کلیدهای مشخص محصول
                for key in ("title_fa", "title_en"):
                    value = node.get(key)
                    if isinstance(value, str) and value.strip():
                        found["title"] = value.strip()
                        break
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    if "price" not in found:
        return None
    return to_toman(found["price"], "next_data", None, policy), found.get("title")


def price_from_css(soup: BeautifulSoup) -> tuple[int, str] | None:
    for selector in SELECTORS["price"]:
        try:
            elements = soup.select(selector)
        except Exception:
            continue
        for element in elements:
            price = utils.parse_price_text(element.get_text(" ", strip=True))
            if price and price > 0:
                return price, selector
    return None


def clean_title(title: str | None) -> Optional[str]:
    """پاک‌سازی عنوان (فاصله‌های اضافی و پسوند «| دیجی کالا»)."""
    if not title:
        return None
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"\s*[|\-–]\s*دیجی\s*کالا\s*$", "", title).strip()
    return title or None


def title_from_page(soup: BeautifulSoup) -> Optional[str]:
    for selector in SELECTORS["title"]:
        try:
            element = soup.select_one(selector)
        except Exception:
            continue
        if element is None:
            continue
        if element.has_attr("content"):
            text = element["content"]
        else:
            text = element.get_text(strip=True)
        if text:
            return clean_title(str(text))
    return None


def extract_from_html(html_text: str, price_unit: str = "auto") -> ProductInfo:
    """تحلیل HTML و استخراج قیمت/عنوان؛ در شکست ScrapeError مناسب می‌دهد."""
    if not html_text:
        raise PriceNotFound("محتوای صفحه خالی است.")

    soup = _soup(html_text)
    price: int | None = None
    source = ""
    title: str | None = None

    found = price_from_json_ld(soup, price_unit)
    if found:
        price, title = found
        source = "json_ld"

    if price is None:
        found = price_from_next_data(soup, price_unit)
        if found:
            price, next_title = found
            source = "next_data"
            title = title or clean_title(next_title)

    if price is None:
        found = price_from_css(soup)
        if found:
            price, _selector = found
            source = "css"

    title = title or title_from_page(soup)

    if price is None:
        body_text = soup.get_text(" ", strip=True)
        lowered = body_text.lower()
        if any(marker in body_text for marker in UNAVAILABLE_MARKERS):
            raise ProductUnavailable("نشانه‌ی ناموجود بودن در صفحه پیدا شد.")
        if any(marker in lowered for marker in BLOCK_MARKERS):
            raise SiteBlocked("نشانه‌ی کپچا/بلاک شدن در صفحه پیدا شد.")
        raise PriceNotFound("نه از داده‌های ساختاریافته و نه از سلکتورهای CSS قیمت پیدا نشد.")

    if price <= 0:
        raise PriceNotFound("قیمت استخراج‌شده نامعتبر است.")
    if price < 100:
        log.warning(
            "قیمت مشکوک (%d تومان) استخراج شد؛ احتمالاً واحد قیمت اشتباه تشخیص داده شده است.",
            price,
        )

    return ProductInfo(title=title, price_toman=price, source=source)


# ---------------------------------------------------------------------------
# موتورها
# ---------------------------------------------------------------------------


class BaseScraper(ABC):
    """قرارداد موتور استخراج؛ برای موتور جدید فقط همین دو متد را پیاده‌سازی کنید."""

    @abstractmethod
    async def fetch(self, url: str) -> ProductInfo:
        """صفحه را باز می‌کند و (عنوان، قیمت به تومان) برمی‌گرداند."""

    @abstractmethod
    async def close(self) -> None:
        """منابع مرورگر را آزاد می‌کند."""


class PyppeteerScraper(BaseScraper):
    """موتور پیش‌فرض با pyppeteer؛ یک مرورگر ماندگار + صفحات موقت."""

    def __init__(self, settings: ScraperSettings | None = None) -> None:
        self.settings = settings or ScraperSettings()
        self._browser = None
        self._launch_lock = asyncio.Lock()
        self._page_semaphore = asyncio.Semaphore(
            max(1, self.settings.max_concurrent_pages)
        )

    async def _get_browser(self):
        import pyppeteer  # ایمپورت سنگین فقط همین‌جا و به‌صورت lazy انجام می‌شود

        async with self._launch_lock:
            if self._browser is None:
                launch_kwargs: dict = {
                    "headless": self.settings.headless,
                    "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
                    "logLevel": logging.WARNING,
                }
                if self.settings.chrome_executable_path:
                    launch_kwargs["executablePath"] = self.settings.chrome_executable_path
                try:
                    self._browser = await pyppeteer.launch(**launch_kwargs)
                except Exception as exc:
                    raise BrowserUnavailable(
                        "اجرای Chromium ممکن نشد؛ راهنمای نصب مرورگر را در README ببینید."
                    ) from exc
            return self._browser

    def _reset_browser(self) -> None:
        self._browser = None

    async def _sleep_backoff(self, attempt: int) -> None:
        delay = self.settings.retry_backoff_seconds * attempt + random.uniform(0, 1.5)
        await asyncio.sleep(delay)

    async def fetch(self, url: str) -> ProductInfo:
        """استخراج با تلاش محدود؛ خطاهای غیرقابل بازگشت مستقیم بالا می‌روند."""
        attempt = 0
        while True:
            attempt += 1
            try:
                return await self._fetch_once(url)
            except (SiteBlocked, ProductUnavailable, PriceNotFound, BrowserUnavailable):
                raise  # با تلاش دوباره بهتر نمی‌شوند
            except ScrapeTimeout:
                if attempt >= self.settings.retry_attempts:
                    raise
                log.warning("تایم‌اوت بارگذاری صفحه (تلاش %d)؛ دوباره تلاش می‌شود.", attempt)
                await self._sleep_backoff(attempt)
            except Exception as exc:
                # معمولاً یعنی مرورگر/تب ناگهان بسته شده؛ مرورگر را نو می‌کنیم
                self._reset_browser()
                if attempt >= self.settings.retry_attempts:
                    raise ScrapeError(f"بارگذاری صفحه ناموفق ماند: {exc}") from exc
                log.warning("خطای موتور مرورگر (تلاش %d): %r", attempt, exc)
                await self._sleep_backoff(attempt)

    async def _fetch_once(self, url: str) -> ProductInfo:
        browser = await self._get_browser()
        async with self._page_semaphore:
            page = await browser.newPage()
            try:
                await page.setUserAgent(self.settings.user_agent)
                await page.setViewport(
                    {
                        "width": self.settings.viewport_width,
                        "height": self.settings.viewport_height,
                    }
                )
                await page.setExtraHTTPHeaders(
                    {"Accept-Language": self.settings.accept_language}
                )
                timeout_ms = int(self.settings.page_timeout_seconds * 1000)
                try:
                    await page.goto(
                        url,
                        options={"waitUntil": "domcontentloaded", "timeout": timeout_ms},
                    )
                except asyncio.TimeoutError as exc:
                    raise ScrapeTimeout("زمان بارگذاری صفحه به پایان رسید.") from exc
                except Exception as exc:
                    # pyppeteer.errors.TimeoutError هم نام کلاسش TimeoutError است
                    if type(exc).__name__ == "TimeoutError":
                        raise ScrapeTimeout("زمان بارگذاری صفحه به پایان رسید.") from exc
                    raise
                await asyncio.sleep(1.2)  # فرصت کوچک برای رندر اولیه
                html_text = await page.content()
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
        try:
            return extract_from_html(html_text, self.settings.price_unit)
        except ScrapeError:
            raise
        except Exception as exc:
            raise PriceNotFound(f"خطا در تحلیل صفحه: {exc}") from exc

    async def close(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None


class DummyScraper(BaseScraper):
    """موتور آزمایشی بدون Chromium برای تست ربات (SCRAPE_BACKEND=dummy).

    قیمت شبه‌تصادفی می‌سازد که با هر بررسی کمی تغییر می‌کند تا مسیر اعلان
    تغییر قیمت هم قابل تست باشد. برای استفاده‌ی واقعی نیست.
    """

    def __init__(self, settings: ScraperSettings | None = None) -> None:
        self.settings = settings or ScraperSettings()
        self._last_price: dict[str, int] = {}

    async def fetch(self, url: str) -> ProductInfo:
        match = re.search(r"dkp-(\d+)", url, re.IGNORECASE)
        code = match.group(1) if match else url[-12:]
        if code.isdigit():
            base_price = 1_000_000 + (int(code) % 500) * 1_000_000
        else:
            base_price = 25_000_000
        current = self._last_price.get(code, base_price)
        drift = int(current * random.uniform(-0.03, 0.03))
        if abs(drift) < 1_000:
            drift = random.choice([-1, 1]) * random.randint(1, 50) * 1_000
        current = max(1_000, current + drift)
        self._last_price[code] = current
        await asyncio.sleep(random.uniform(0.2, 0.8))  # شبیه‌سازی تأخیر شبکه
        return ProductInfo(
            title=f"محصول آزمایشی شماره {code}",
            price_toman=current,
            source="dummy",
        )

    async def close(self) -> None:
        self._last_price.clear()


BUILDERS: dict[str, type[BaseScraper]] = {
    "pyppeteer": PyppeteerScraper,
    "dummy": DummyScraper,
}


def build_scraper(backend: str, settings: ScraperSettings | None = None) -> BaseScraper:
    """ساخت موتور استخراج بر اساس SCRAPE_BACKEND."""
    factory = BUILDERS.get(backend)
    if factory is None:
        raise ValueError(
            f"موتور استخراج «{backend}» تعریف نشده است؛ موتورهای موجود: {sorted(BUILDERS)}"
        )
    return factory(settings)
