# Digipup — ربات رصد قیمت دیجی‌کالا (Docker)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Tehran \
    DB_PATH=/data/digipup.db \
    PYPPETEER_HOME=/data/pyppeteer \
    CHROME_EXECUTABLE_PATH=/usr/bin/chromium

# Chromium و فونت‌ها و داده‌ی منطقه‌ی زمانی
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium tzdata fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# کاربر غیر root + پوشه‌ی داده‌ی ماندگار
RUN useradd --create-home bot \
    && mkdir -p /data \
    && chown -R bot:bot /data /app
USER bot

VOLUME ["/data"]
CMD ["python", "bot.py"]
