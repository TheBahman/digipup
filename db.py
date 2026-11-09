"""لایه‌ی پایگاه داده‌ی Digipup — SQLite با aiosqlite (کاملاً async).

مدل داده:
    users(user_id, username, created_at)
    products(id, user_id, product_code, url, title, interval_minutes,
             is_active, created_at, last_checked_at)
    price_history(id, product_id, price, checked_at)

نکات امنیتی:
- همه‌ی کوئری‌ها پارامتری هستند (بدون ساخت رشته‌ی SQL از ورودی کاربر).
- UNIQUE(user_id, product_code) جلوی ثبت لینک تکراری برای یک کاربر را می‌گیرد.
- کلید خارجی price_history با ON DELETE CASCADE، حذف تاریخچه را تضمین می‌کند.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiosqlite

log = logging.getLogger("digipup.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    product_code     TEXT NOT NULL,
    url              TEXT NOT NULL,
    title            TEXT,
    interval_minutes INTEGER NOT NULL DEFAULT 30,
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    last_checked_at  TEXT,
    UNIQUE (user_id, product_code)
);

CREATE TABLE IF NOT EXISTS price_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    price      INTEGER NOT NULL,
    checked_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_user   ON products(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_history_product ON price_history(product_id, checked_at DESC);
"""


def utcnow_iso() -> str:
    """زمان فعلی UTC به شکل ISO برای ذخیره‌ی یکدست در SQLite."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """پوشش async روی SQLite؛ یک اتصال ماندگار برای کل عمر ربات."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    # ------------------------------------------------------------- اتصال
    async def connect(self) -> None:
        if self._conn is not None:
            return
        self._conn = await aiosqlite.connect(self._path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(SCHEMA)
        log.info("پایگاه داده آماده شد: %s", self._path)

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.close()
            finally:
                self._conn = None
                log.info("اتصال پایگاه داده بسته شد.")

    # ------------------------------------------------------- ابزار داخلی
    async def _fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        assert self._conn is not None, "قبل از کوئری باید connect() صدا زده شود"
        async with self._conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        assert self._conn is not None, "قبل از کوئری باید connect() صدا زده شود"
        async with self._conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def _execute(self, sql: str, params: tuple = ()) -> int | None:
        assert self._conn is not None, "قبل از کوئری باید connect() صدا زده شود"
        async with self._conn.execute(sql, params) as cursor:
            return cursor.lastrowid

    # ------------------------------------------------------------- users
    async def upsert_user(self, user_id: int, username: str | None) -> None:
        await self._execute(
            "INSERT INTO users (user_id, username, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username = excluded.username",
            (int(user_id), username, utcnow_iso()),
        )

    # ---------------------------------------------------------- products
    async def add_product(
        self,
        user_id: int,
        product_code: str,
        url: str,
        title: str | None,
        interval_minutes: int,
    ) -> int | None:
        """ثبت محصول جدید؛ اگر برای این کاربر تکراری باشد None برمی‌گرداند."""
        try:
            return await self._execute(
                "INSERT INTO products "
                "(user_id, product_code, url, title, interval_minutes, is_active, created_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?)",
                (int(user_id), product_code, url, title, int(interval_minutes), utcnow_iso()),
            )
        except aiosqlite.IntegrityError:
            return None

    async def get_product(self, product_id: int) -> dict | None:
        return await self._fetchone(
            "SELECT * FROM products WHERE id = ?",
            (int(product_id),),
        )

    async def get_product_by_code(self, user_id: int, product_code: str) -> dict | None:
        return await self._fetchone(
            "SELECT * FROM products WHERE user_id = ? AND product_code = ?",
            (int(user_id), product_code),
        )

    async def list_products(self, user_id: int) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM products WHERE user_id = ? ORDER BY created_at ASC, id ASC",
            (int(user_id),),
        )

    async def list_active_products(self) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM products WHERE is_active = 1 ORDER BY last_checked_at ASC"
        )

    async def set_interval(self, product_id: int, minutes: int) -> None:
        await self._execute(
            "UPDATE products SET interval_minutes = ? WHERE id = ?",
            (int(minutes), int(product_id)),
        )

    async def set_active(self, product_id: int, is_active: bool) -> None:
        await self._execute(
            "UPDATE products SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, int(product_id)),
        )

    async def set_title(self, product_id: int, title: str) -> None:
        await self._execute(
            "UPDATE products SET title = ? WHERE id = ?",
            (title, int(product_id)),
        )

    async def touch_checked(self, product_id: int, when_iso: str | None = None) -> None:
        """ثبت زمان آخرین بررسی (موفق یا ناموفق) برای محاسبه‌ی بررسی بعدی."""
        await self._execute(
            "UPDATE products SET last_checked_at = ? WHERE id = ?",
            (when_iso or utcnow_iso(), int(product_id)),
        )

    async def delete_product(self, product_id: int) -> None:
        # تاریخچه‌ی قیمت با ON DELETE CASCADE خودکار پاک می‌شود
        await self._execute(
            "DELETE FROM products WHERE id = ?",
            (int(product_id),),
        )

    # ------------------------------------------------------ price_history
    async def insert_price(self, product_id: int, price: int) -> None:
        await self._execute(
            "INSERT INTO price_history (product_id, price, checked_at) VALUES (?, ?, ?)",
            (int(product_id), int(price), utcnow_iso()),
        )

    async def get_last_price(self, product_id: int) -> dict | None:
        return await self._fetchone(
            "SELECT price, checked_at FROM price_history "
            "WHERE product_id = ? ORDER BY checked_at DESC, id DESC LIMIT 1",
            (int(product_id),),
        )

    async def get_first_price(self, product_id: int) -> dict | None:
        return await self._fetchone(
            "SELECT price, checked_at FROM price_history "
            "WHERE product_id = ? ORDER BY checked_at ASC, id ASC LIMIT 1",
            (int(product_id),),
        )

    async def get_price_stats(self, product_id: int) -> dict | None:
        row = await self._fetchone(
            "SELECT COUNT(*) AS checks, MIN(price) AS min_price, "
            "MAX(price) AS max_price, AVG(price) AS avg_price "
            "FROM price_history WHERE product_id = ?",
            (int(product_id),),
        )
        if row is None or row["checks"] == 0:
            return None
        return row

    async def get_recent_history(self, product_id: int, limit: int = 7) -> list[dict]:
        return await self._fetchall(
            "SELECT price, checked_at FROM price_history "
            "WHERE product_id = ? ORDER BY checked_at DESC, id DESC LIMIT ?",
            (int(product_id), int(limit)),
        )

    async def count_history(self, product_id: int) -> int:
        row = await self._fetchone(
            "SELECT COUNT(*) AS n FROM price_history WHERE product_id = ?",
            (int(product_id),),
        )
        return int(row["n"]) if row else 0
