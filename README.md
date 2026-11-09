# 🐾 Digipup — ربات رصد قیمت دیجی‌کالا با Python + pyppeteer

ربات تلگرامی که لینک هر محصول دیجی‌کالا را می‌گیرد، با **pyppeteer** (پورت پایتونی Puppeteer) صفحه‌ی محصول را باز می‌کند، **عنوان و قیمت فعلی** را استخراج و در **SQLite** ذخیره می‌کند و در بازه‌های **۱۵ دقیقه، ۳۰ دقیقه، ۱ ساعت، ۲ ساعت یا ۶ ساعت** قیمت را دوباره چک می‌کند. با هر تغییر قیمت، پیامی با **ایموجی و اعداد فارسی** شامل درصد تغییر، قیمت قبلی، قیمت جدید و ساعت بررسی می‌فرستد.

ربات محترمانه کار می‌کند: User-Agent معمولی، تایم‌اوت مشخص، تعداد تلاش محدود، حداکثر ۲ صفحه‌ی هم‌زمان، بازه‌ی حداقلی ۱۵ دقیقه و jitter تصادفی ±۳۰ ثانیه. هیچ تلاشی برای دور زدن محافظت‌های سایت انجام نمی‌شود.

---

## ✨ ویژگی‌ها

- ➕ افزودن محصول با اعتبارسنجی لینک و استخراج `product_code` از الگوی `dkp-…`
- 🚫 جلوگیری از ثبت لینک تکراری برای هر کاربر (`UNIQUE(user_id, product_code)`)
- ⏱ بازه‌ی بررسی مستقل برای هر محصول + پیش‌فرض ۳۰ دقیقه
- 🔍 «بررسی فوری قیمت» دستی برای هر محصول
- 🔔 فعال/غیرفعال کردن رصد هر محصول
- 🗑 حذف محصول با تأیید (به‌همراه کل تاریخچه)
- 📊 گزارش قیمت: کمینه، بیشینه، میانگین، درصد تغییر نسبت به شروع رصد و بررسی‌های اخیر
- 📈 اعلان تغییر قیمت با درصد رشد/کاهش، قیمت قبلی/جدید و ساعت به‌وقت تهران
- 📦 اعلان «ناموجود شدن» و «دوباره موجود شدن» محصول
- 🔐 خواندن توکن از `.env`، کوئری‌های SQL پارامتری، فرار HTML همه‌ی ورودی‌ها، لاگ بدون توکن

---

## 🏗 معماری پروژه

```
digipup/
├── bot.py            # نقطه‌ی ورود؛ هندلرهای دستور/منو/کال‌بک و سیم‌کشی جاب دوره‌ای
├── config.py         # خواندن و اعتبارسنجی تنظیمات از .env
├── db.py             # لایه‌ی SQLite (aiosqlite): users / products / price_history
├── scraper.py        # لایه‌ی استخراج قیمت (pyppeteer؛ قابل تعویض با Playwright یا Node.js)
├── scheduler.py      # جاب هر دقیقه + منطق اعلان تغییر قیمت و قفل ضد اجرای هم‌زمان
├── keyboards.py      # منوی اصلی (Reply) و پنل‌ها/دکمه‌های اینلاین
├── utils.py          # اعداد فارسی، قالب‌بندی تومان، اعتبارسنجی لینک، قالب پیام‌ها
├── requirements.txt
├── .env.example
├── Dockerfile
└── README.md
```

### لایه‌ها و جریان داده

```
کاربر ──لینک──▶ bot.py ──اعتبارسنجی (utils.parse_digikala_url)──▶ db.products
                    │
                    └─▶ scraper.py  (pyppeteer → JSON-LD / __NEXT_DATA__ / CSS)
                                     │
scheduler.tick (هر ۶۰ ثانیه) ────────┘
   │  محصولات موعددار (is_active=1 و بازه+jitter سپری شده)
   ├─▶ scraper.fetch(url)
   ├─▶ db.insert_price(...)  و  db.touch_checked(...)
   └─▶ قیمت تغییر کرد؟ ─▶ پیام 📈/📉 با درصد، قیمت قبلی/جدید و ساعت تهران
```

**اصل جداسازی:** لایه‌ی استخراج یک قرارداد ساده دارد (`BaseScraper.fetch/close`). هیچ ماژول دیگری مستقیماً مرورگر را صدا نمی‌زند؛ به همین دلیل تعویض موتور با Playwright یا سرویس Node.js فقط با افزودن یک کلاس و تغییر یک متغیر محیطی انجام می‌شود (بخش «تعویض لایه‌ی استخراج»).

### ترتیب استخراج قیمت

1. **JSON-LD** (`schema.org/Product` → `offers.price` همراه تشخیص `priceCurrency`)
2. **`__NEXT_DATA__`** (فیلد `selling_price` واریانت محصول + `title_fa`)
3. **سلکتورهای CSS** از دیکشنری `SELECTORS` در `scraper.py` (متن «عدد + تومان»)
4. متای صفحه فقط برای **عنوان** (`og:title` و مشابه)

همیشه فقط **عدد قیمت به تومان** (بدون کاما) و **عنوان** ذخیره می‌شود.

---

## 📋 پیش‌نیازها

- Python **3.11+**
- یک توکن ربات از [@BotFather](https://t.me/BotFather)
- **Chrome/Chromium** برای pyppeteer (بخش بعدی)

---

## 🚀 نصب و اجرا (لوکال)

```bash
cd digipup

# محیط مجازی
python3 -m venv .venv
source .venv/bin/activate        # ویندوز: .venv\Scripts\activate

# وابستگی‌ها
pip install -r requirements.txt

# تنظیمات
cp .env.example .env
#  فایل .env را باز کنید و BOT_TOKEN واقعی را بگذارید

# اجرا
python bot.py
```

ربات با `run_polling` اجرا می‌شود؛ جاب بررسی قیمت ۱۰ ثانیه پس از بالا آمدن شروع می‌شود و سپس هر ۶۰ ثانیه محصولات موعددار را چک می‌کند.

### 🌐 نصب Chromium برای pyppeteer

**گزینه ۱ — دانلود خودکار (پیش‌فرض):** در اولین اجرا، pyppeteer نسخه‌ی سازگار Chromium را دانلود می‌کند (حدود ۱۵۰ مگابایت) و در `~/.local/share/pyppeteer` ذخیره می‌کند. برای دانلود از قبل:

```bash
pyppeteer-install          # یا: python -m pyppeteer.install
```

مسیر دانلود را می‌توانید با متغیر `PYPPETEER_HOME` تغییر دهید.

**گزینه ۲ — استفاده از Chromium سیستم (پیشنهادی برای سرور):**

```bash
# Debian/Ubuntu
sudo apt install chromium
# سپس در .env:
# CHROME_EXECUTABLE_PATH=/usr/bin/chromium
```

- **macOS:** `brew install chromium` و سپس `CHROME_EXECUTABLE_PATH=/Applications/Chromium.app/Contents/MacOS/Chromium`
- **Windows:** مسیر `chrome.exe` یا `chromium.exe` را در `CHROME_EXECUTABLE_PATH` بگذارید.

### 🧪 اجرا بدون Chromium (تست منطق ربات)

```env
SCRAPE_BACKEND=dummy
```

موتور آزمایشی قیمت شبه‌تصادفی می‌سازد (با تغییر تدریجی) تا همه‌ی مسیرها — حتی اعلان تغییر قیمت — بدون مرورگر قابل تست باشند.

---

## 🐳 اجرا با Docker

```bash
docker build -t digipup .
docker run -d --name digipup \
  -e BOT_TOKEN="توکن_ربات_شما" \
  -v digipup-data:/data \
  digipup

docker logs -f digipup
```

ایمیج از `python:3.11-slim` ساخته می‌شود، Chromium با apt نصب می‌شود (`CHROME_EXECUTABLE_PATH=/usr/bin/chromium`)، پایگاه داده در volume‌ی `/data` ماندگار است و فرایند با کاربر غیر root اجرا می‌شود.

---

## ⚙️ متغیرهای محیطی

| متغیر | پیش‌فرض | توضیح |
|---|---|---|
| `BOT_TOKEN` | — (**اجباری**) | توکن ربات از @BotFather |
| `DB_PATH` | `digipup.db` | مسیر فایل SQLite |
| `TZ_NAME` | `Asia/Tehran` | منطقه‌ی زمانی نمایش ساعت در پیام‌ها |
| `LOG_LEVEL` | `INFO` | سطح لاگ |
| `SCRAPE_BACKEND` | `pyppeteer` | `pyppeteer` یا `dummy` (تست بدون مرورگر) |
| `CHROME_EXECUTABLE_PATH` | خالی | مسیر مرورگر سیستمی؛ خالی = مدیریت خودکار pyppeteer |
| `HEADLESS` | `true` | اجرای بی‌سر مرورگر |
| `PAGE_TIMEOUT_SECONDS` | `45` | تایم‌اوت بارگذاری صفحه |
| `MAX_CONCURRENT_PAGES` | `2` | سقف صفحه‌ی هم‌زمان |
| `RETRY_ATTEMPTS` | `2` | تعداد تلاش روی تایم‌اوت/خطای گذرا |
| `RETRY_BACKOFF_SECONDS` | `3` | فاصله‌ی backoff بین تلاش‌ها |
| `USER_AGENT` | Chrome ویندوزی | User-Agent معمولی |
| `PRICE_UNIT` | `auto` | `auto` / `toman` / `rrial` (بخش ریال/تومان) |
| `DEFAULT_INTERVAL_MINUTES` | `30` | بازه‌ی پیش‌فرض پس از افزودن |
| `MIN_INTERVAL_MINUTES` | `15` | حداقل بازه‌ی مجاز |
| `INTERVAL_CHOICES` | `15,30,60,120,360` | گزینه‌های منوی تنظیم بازه |
| `JITTER_SECONDS` | `30` | jitter تصادفی ±۳۰ ثانیه |
| `SCHEDULER_TICK_SECONDS` | `60` | فاصله‌ی اجرای جاب زمان‌بند |
| `NOTIFY_ON_NO_CHANGE` | `false` | اعلان اختیاری وقتی قیمت تغییر نکرد |
| `ERROR_NOTIFY_EVERY` | `6` | پیام خطای استخراج: بار اول و هر N خطای متوالی |

---

## 🧭 منوها و جریان کاربری

- **`/start`** — پیام خوش‌آمد + منوی اصلی (Reply Keyboard):
  `➕ افزودن محصول | 📋 لیست محصولات من | ⏱ تنظیم بازه بررسی | 🔔 وضعیت رصد | 🗑 حذف محصول | 📊 گزارش قیمت | ℹ️ راهنما`
- **➕ افزودن محصول** — ربات لینک می‌خواهد؛ لینک اعتبارسنجی و کد `dkp-…` استخراج می‌شود. استخراج اولیه‌ی قیمت انجام و محصول ثبت می‌شود (پیش‌فرض ۳۰ دقیقه). می‌توانید لینک را مستقیم هم در چت بفرستید.
- **📋 لیست محصولات من** — لیست با آخرین قیمت؛ لمس هر محصول، پنل مدیریتی را باز می‌کند: `🔍 بررسی فوری | ⏱ تغییر بازه | 🔔/🔕 فعال‌سازی | 📊 گزارش | 🗑 حذف`
- **⏱ تنظیم بازه بررسی** — انتخاب محصول، سپس یکی از ۱۵ دقیقه / ۳۰ دقیقه / ۱ ساعت / ۲ ساعت / ۶ ساعت.
- **🔔 وضعیت رصد** — لیست با وضعیت ✅/⏸؛ لمس هر محصول، رصدش را فعال/غیرفعال می‌کند.
- **🗑 حذف محصول** — انتخاب محصول + پیام تأیید («🔥 بله، حذف کن / 😌 نه»).
- **📊 گزارش قیمت** — آمار کامل و ۷ بررسی اخیر.
- **دستورات:** `/start`، `/help`، `/cancel`.

---

## 💬 قالب پیام‌ها

پیام تغییر قیمت:

```
📱 گوشی Samsung Galaxy S23 Ultra
⏰ ساعت ۱۴:۴۵
📈 رشد قیمت: ۳٪
💰 قیمت قبلی: ۲۰۷ میلیون تومان
💵 قیمت جدید: ۲۱۳ میلیون و ۲۱۰ هزار تومان
🔗 لینک محصول
```

- کاهش قیمت با **📉 کاهش قیمت** نمایش داده می‌شود.
- قیمت‌ها به شکل خوانا «میلیارد/میلیون/هزار تومان» قالب‌بندی می‌شوند.
- پیام‌های خطا:
  - لینک نامعتبر: `❌ لطفاً یک لینک معتبر محصول دیجی‌کالا بفرست.`
  - محصول تکراری: `⚠️ این محصول قبلاً برای شما ثبت شده است.`
  - خطای استخراج: `⚠️ فعلاً نتوانستم قیمت را بخوانم. کمی بعد دوباره تلاش می‌کنم.`
  - دسترسی/بلاک: `🚫 سایت پاسخ معتبر نداد؛ بررسی بعدی طبق زمان‌بندی انجام می‌شود.`
  - ناموجود شدن: `📦 این محصول در دیجی‌کالا ناموجود شده است 😕`

---

## 🧮 مدل داده

```sql
users         (user_id PK, username, created_at)
products      (id PK, user_id, product_code, url, title,
               interval_minutes, is_active, created_at, last_checked_at,
               UNIQUE(user_id, product_code))
price_history (id PK, product_id FK→products ON DELETE CASCADE,
               price, checked_at)
```

- هر کاربر چند محصول و هر محصول بازه‌ی مستقل دارد.
- لینک تکراری برای یک کاربر ثبت نمی‌شود.
- همه‌ی زمان‌ها به UTC ذخیره و در پیام‌ها به وقت تهران نمایش داده می‌شوند.

---

## 🎯 افزودن سلکتور جدید قیمت

همه‌ی سلکتورها در دیکشنری **`SELECTORS`** بالای `scraper.py` هستند:

```python
SELECTORS: dict[str, list[str]] = {
    "price": [
        '[data-testid="price-current"]',   # اولویت اول
        '[data-testid="price-no-discount"]',
        '[data-testid="price-final"]',
        '[data-testid="price"]',
        ".price-inside-text",
    ],
    "title": ['[data-testid="product-title"]', ...],
}
```

**روش:** سلکتور جدید را به **ابتدای** لیست `"price"` اضافه کنید؛ موتور به ترتیب امتحان می‌کند و اولین عنصری که متنش شامل «عدد + تومان» باشد (`utils.parse_price_text`) پذیرفته می‌شود. شرط کافی برای کارکرد سلکتور: متن عنصر قیمت را شامل باشد، مثل `۲۱۳٬۲۱۰٬۰۰۰ تومان` (ارقام فارسی، کامای فارسی و فاصله هم پشتیبانی می‌شوند).

اگر ساختار سایت آن‌قدر عوض شده باشد که JSON-LD و `__NEXT_DATA__` هم کار نکنند، استخراج به همین سلکتورهای CSS برمی‌گردد؛ کافی است سلکتور درست را پیدا کنید (DevTools مرورگر → inspect عنصر قیمت) و به لیست اضافه کنید. برای عناوین هم لیست `"title"` همین‌طور قابل گسترش است.

---

## 🔁 تعویض لایه‌ی استخراج (Playwright یا سرویس Node.js)

اگر pyppeteer روی سرور شما ناپایدار بود، لایه‌ی `scraper` طوری طراحی شده که بدون تغییر بقیه‌ی پروژه عوض شود. کافی است:

1. یک زیرکلاس از `BaseScraper` با دو متد `fetch` و `close` بنویسید (برای تحلیل HTML همان `extract_from_html` قابل استفاده‌ی مجدد است).
2. کلاس را در دیکشنری `BUILDERS` انتهای `scraper.py` ثبت کنید.
3. در `.env` بگذارید: `SCRAPE_BACKEND=<نام جدید>`

### گزینه‌ی الف — Playwright

```bash
pip install playwright
playwright install chromium
```

```python
# در scraper.py
from playwright.async_api import async_playwright

class PlaywrightScraper(BaseScraper):
    def __init__(self, settings=None):
        self.settings = settings or ScraperSettings()
        self._pw = None
        self._browser = None

    async def _ensure(self):
        if self._browser is None:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self.settings.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                executable_path=self.settings.chrome_executable_path or None,
            )
        return self._browser

    async def fetch(self, url: str) -> ProductInfo:
        browser = await self._ensure()
        page = await browser.new_page(
            user_agent=self.settings.user_agent,
            locale="fa-IR",
            viewport={"width": 1366, "height": 850},
        )
        try:
            await page.goto(url, wait_until="domcontentloaded",
                            timeout=self.settings.page_timeout_seconds * 1000)
            await page.wait_for_timeout(1200)
            html_text = await page.content()
        finally:
            await page.close()
        return extract_from_html(html_text, self.settings.price_unit)

    async def close(self):
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._pw:
            await self._pw.stop()

BUILDERS["playwright"] = PlaywrightScraper   # و در .env:  SCRAPE_BACKEND=playwright
```

### گزینه‌ی ب — سرویس Node.js/Puppeteer

یک میکروسرویس کوچک بسازید و HTML را از طریق HTTP بگیرید (پکیج `httpx` همراه python-telegram-bot نصب می‌شود):

```js
// scraper-service.js  →  npm i express puppeteer
const express = require("express");
const puppeteer = require("puppeteer");
const app = express();
app.use(express.json());

let browser;
app.post("/fetch", async (req, res) => {
  try {
    if (!browser) browser = await puppeteer.launch({ args: ["--no-sandbox"] });
    const page = await browser.newPage();
    if (req.body.user_agent) await page.setUserAgent(req.body.user_agent);
    await page.goto(req.body.url, { waitUntil: "domcontentloaded", timeout: 45000 });
    const html = await page.content();
    await page.close();
    res.json({ html });
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});
app.listen(8080);
```

```python
# در scraper.py
import httpx

class RemoteNodeScraper(BaseScraper):
    """موتور استخراج با سرویس Node.js/Puppeteer روی localhost:8080"""

    async def fetch(self, url: str) -> ProductInfo:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post("http://127.0.0.1:8080/fetch", json={
                "url": url,
                "user_agent": self.settings.user_agent,
            })
            response.raise_for_status()
            html_text = response.json()["html"]
        return extract_from_html(html_text, self.settings.price_unit)

    async def close(self):
        pass

BUILDERS["remote_node"] = RemoteNodeScraper  # و در .env:  SCRAPE_BACKEND=remote_node
```

---

## 💱 نکته‌ی ریال/تومان (`PRICE_UNIT`)

دیجی‌کالا به‌طور سنتی قیمت‌های ساختاریافته (JSON-LD / API) را به **ریال** و قیمت نمایش‌داده‌شده‌ی صفحه را به **تومان** منتشر می‌کند. حالت `auto` این را تشخیص می‌دهد:

- اگر `priceCurrency` صریحاً `IRR/RIAL` باشد → تقسیم بر ۱۰
- اگر `IRT/TOMAN` باشد → بدون تغییر
- در نبود ارز: داده‌های ساختاریافته ریال فرض می‌شوند (÷۱۰)، متن CSS با پسوند «تومان» دست‌نخورده می‌ماند.

اگر قیمت‌های ذخیره‌شده **۱۰ برابر بزرگ‌تر** از سایت بودند، `PRICE_UNIT=toman` بگذارید؛ اگر **۱۰ برابر کوچک‌تر** بودند، `PRICE_UNIT=rrial`. قیمت‌های زیر ۱۰۰ تومان در لاگ هشدار می‌گیرند.

---

## ⚠️ محدودیت‌ها و ملاحظات

- **تغییر ساختار صفحه:** دیجی‌کالا هر از گاهی ظاهر سایت و داده‌های داخلی را عوض می‌کند؛ ممکن است استخراج موقتاً ناموفق شود. راه‌حل: به‌روزرسانی `SELECTORS` در `scraper.py`.
- **بلاک شدن:** اگر سایت پاسخ 403/429 بدهد یا کپچا نشان دهد، ربات تلاشی برای دور زدن نمی‌کند و پیام 🚫 می‌دهد؛ بررسی بعدی طبق زمان‌بندی انجام می‌شود.
- **نرخ درخواست:** حداقل بازه ۱۵ دقیقه + jitter ±۳۰ ثانیه + سقف ۲ صفحه‌ی هم‌زمان + تلاش محدود. لطفاً این‌ها را سخت‌گیرتر نکنید.
- **pyppeteer:** نگه‌داری آن کند است و روی بعضی سرورها ناپایدار است؛ اگر مشکل داشتید از راهنمای «تعویض لایه‌ی استخراج» استفاده کنید.
- **محدوده‌ی استفاده:** فقط صفحات عمومی محصول رصد می‌شوند؛ هیچ ورود/احراز هویتی انجام نمی‌شود.

## 🤝 استفاده‌ی مسئولانه

استفاده از این ربات باید مطابق **قوانین و شرایط استفاده‌ی دیجی‌کالا** و ملاحظات **حریم خصوصی** باشد. این پروژه برای رصد شخصی و آموزشی طراحی شده است؛ از افزایش نرخ درخواست‌ها، رصد انبوه یا هر استفاده‌ای که به سایت فشار وارد کند خودداری کنید.

---

## 🧯 عیب‌یابی

| مشکل | راه‌حل |
|---|---|
| `BOT_TOKEN تنظیم نشده است` | فایل `.env` را کنار کد بسازید و توکن را بگذارید |
| `اجرای Chromium ممکن نشد` | `pyppeteer-install` را اجرا کنید یا `CHROME_EXECUTABLE_PATH` را به مرورگر سیستمی بدهید |
| `python-telegram-bot با اکسترا [job-queue] نصب نشده` | `pip install "python-telegram-bot[job-queue]"` |
| تایم‌اوت‌های مکرر | `PAGE_TIMEOUT_SECONDS` را افزایش دهید؛ شبکه/پروکسی سرور را بررسی کنید |
| قیمت‌ها ۱۰ برابر بزرگ/کوچک | بخش `PRICE_UNIT` را بخوانید |
| پیام خطای ⚠️ تکراری | طبیعی است؛ فقط بار اول و هر `ERROR_NOTIFY_EVERY` خطای متوالی پیام می‌آید و تا رفع مشکل بررسی طبق بازه ادامه دارد |
| پیام‌ها نمی‌آیند | `LOG_LEVEL=DEBUG`؛ بررسی کنید محصول ✅ فعال است و کاربر ربات را بلاک نکرده باشد |
