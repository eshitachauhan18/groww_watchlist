"""SQLite persistence: accounts, sessions, watchlist, portfolio holdings.

Real accounts (username + hashed password) now own the watchlist/portfolio,
replacing the earlier anonymous "device id" stand-in - state persists across
sessions and devices because it's keyed by an actual authenticated user id.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "watchlist.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'balanced',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist_items (
    user_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT 'US',
    added_at REAL NOT NULL,
    PRIMARY KEY (user_id, symbol)
);

CREATE TABLE IF NOT EXISTS last_seen (
    user_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price REAL NOT NULL,
    score REAL NOT NULL,
    level TEXT NOT NULL,
    seen_at REAL NOT NULL,
    PRIMARY KEY (user_id, symbol)
);

CREATE TABLE IF NOT EXISTS portfolio_holdings (
    user_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT 'US',
    quantity REAL NOT NULL,
    avg_buy_price REAL NOT NULL,
    added_at REAL NOT NULL,
    PRIMARY KEY (user_id, symbol)
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


_conn = get_connection()
# FastAPI runs sync endpoints in a threadpool, so multiple threads can call
# cursor() concurrently on this single shared connection. sqlite3 with
# check_same_thread=False permits cross-thread use but does not serialize
# transactions - concurrent commits can race (observed as "cannot commit -
# no transaction is active"). Serialize all access with a lock.
_lock = threading.Lock()
_conn.executescript(SCHEMA)
# Migration guards: older DBs created before these columns existed won't have
# them yet; CREATE TABLE IF NOT EXISTS alone can't add a column to an
# already-existing table.
for migration in (
    "ALTER TABLE users ADD COLUMN sensitivity TEXT NOT NULL DEFAULT 'balanced'",
    "ALTER TABLE watchlist_items ADD COLUMN market TEXT NOT NULL DEFAULT 'US'",
    "ALTER TABLE portfolio_holdings ADD COLUMN market TEXT NOT NULL DEFAULT 'US'",
    "ALTER TABLE watchlist_items ADD COLUMN market TEXT NOT NULL DEFAULT 'US'",
    "ALTER TABLE watchlist_items ADD COLUMN target_price REAL",
    "ALTER TABLE watchlist_items ADD COLUMN target_direction TEXT",
    "ALTER TABLE watchlist_items ADD COLUMN note TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE watchlist_items ADD COLUMN added_price REAL",
):
    try:
        _conn.execute(migration)
    except sqlite3.OperationalError:
        pass  # column already exists
_conn.commit()


@contextmanager
def cursor() -> Iterator[sqlite3.Cursor]:
    with _lock:
        cur = _conn.cursor()
        try:
            yield cur
            _conn.commit()
        finally:
            cur.close()


# --- accounts & sessions ---

def create_user(user_id: str, username: str, password_hash: str, salt: str) -> None:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, username, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, password_hash, salt, time.time()),
        )


def get_user_by_username(username: str) -> Optional[sqlite3.Row]:
    with cursor() as cur:
        return cur.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def create_session(token_hash: str, user_id: str, ttl_seconds: float) -> None:
    now = time.time()
    with cursor() as cur:
        cur.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, user_id, now, now + ttl_seconds),
        )


def get_session(token_hash: str) -> Optional[sqlite3.Row]:
    with cursor() as cur:
        row = cur.execute(
            "SELECT * FROM sessions WHERE token_hash = ? AND expires_at > ?",
            (token_hash, time.time()),
        ).fetchone()
        return row


def delete_session(token_hash: str) -> None:
    with cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def get_sensitivity(user_id: str) -> str:
    with cursor() as cur:
        row = cur.execute("SELECT sensitivity FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["sensitivity"] if row and row["sensitivity"] else "balanced"


def set_sensitivity(user_id: str, sensitivity: str) -> None:
    with cursor() as cur:
        cur.execute("UPDATE users SET sensitivity = ? WHERE id = ?", (sensitivity, user_id))


# --- watchlist ---

def add_symbol(user_id: str, symbol: str, market: str = "US", added_price: Optional[float] = None) -> None:
    with cursor() as cur:
        # INSERT OR IGNORE makes re-adding the same symbol idempotent under
        # concurrent requests instead of raising an integrity error.
        cur.execute(
            "INSERT OR IGNORE INTO watchlist_items (user_id, symbol, market, added_at, added_price) VALUES (?, ?, ?, ?, ?)",
            (user_id, symbol, market, time.time(), added_price),
        )


def remove_symbol(user_id: str, symbol: str) -> None:
    with cursor() as cur:
        cur.execute(
            "DELETE FROM watchlist_items WHERE user_id = ? AND symbol = ?",
            (user_id, symbol),
        )
        cur.execute(
            "DELETE FROM last_seen WHERE user_id = ? AND symbol = ?",
            (user_id, symbol),
        )


def list_symbols(user_id: str, market: str = "US") -> list[str]:
    with cursor() as cur:
        rows = cur.execute(
            "SELECT symbol FROM watchlist_items WHERE user_id = ? AND market = ? ORDER BY added_at",
            (user_id, market),
        ).fetchall()
    return [r["symbol"] for r in rows]


def get_watchlist_item(user_id: str, symbol: str) -> Optional[sqlite3.Row]:
    with cursor() as cur:
        return cur.execute(
            "SELECT * FROM watchlist_items WHERE user_id = ? AND symbol = ?",
            (user_id, symbol),
        ).fetchone()


def set_alert(user_id: str, symbol: str, target_price: Optional[float], target_direction: Optional[str]) -> None:
    with cursor() as cur:
        cur.execute(
            "UPDATE watchlist_items SET target_price = ?, target_direction = ? WHERE user_id = ? AND symbol = ?",
            (target_price, target_direction, user_id, symbol),
        )


def set_note(user_id: str, symbol: str, note: str) -> None:
    with cursor() as cur:
        cur.execute(
            "UPDATE watchlist_items SET note = ? WHERE user_id = ? AND symbol = ?",
            (note, user_id, symbol),
        )


def all_distinct_symbols() -> list[str]:
    """Every symbol tracked by any user, plus every portfolio holding - used
    to warm the shared quote cache regardless of which user asks first."""
    with cursor() as cur:
        watch_rows = cur.execute("SELECT DISTINCT symbol FROM watchlist_items").fetchall()
        holding_rows = cur.execute("SELECT DISTINCT symbol FROM portfolio_holdings").fetchall()
    return list({r["symbol"] for r in watch_rows} | {r["symbol"] for r in holding_rows})


def get_last_seen(user_id: str, symbol: str) -> Optional[sqlite3.Row]:
    with cursor() as cur:
        return cur.execute(
            "SELECT * FROM last_seen WHERE user_id = ? AND symbol = ?",
            (user_id, symbol),
        ).fetchone()


def set_last_seen(user_id: str, symbol: str, price: float, score: float, level: str) -> None:
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO last_seen (user_id, symbol, price, score, level, seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, symbol)
            DO UPDATE SET price = excluded.price, score = excluded.score,
                          level = excluded.level, seen_at = excluded.seen_at
            """,
            (user_id, symbol, price, score, level, time.time()),
        )


# --- portfolio ---

def upsert_holding(user_id: str, symbol: str, quantity: float, avg_buy_price: float, market: str = "US") -> None:
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO portfolio_holdings (user_id, symbol, market, quantity, avg_buy_price, added_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, symbol)
            DO UPDATE SET quantity = excluded.quantity, avg_buy_price = excluded.avg_buy_price
            """,
            (user_id, symbol, market, quantity, avg_buy_price, time.time()),
        )


def remove_holding(user_id: str, symbol: str) -> None:
    with cursor() as cur:
        cur.execute(
            "DELETE FROM portfolio_holdings WHERE user_id = ? AND symbol = ?",
            (user_id, symbol),
        )


def list_holdings(user_id: str, market: str = "US") -> list[sqlite3.Row]:
    with cursor() as cur:
        return cur.execute(
            "SELECT * FROM portfolio_holdings WHERE user_id = ? AND market = ? ORDER BY added_at",
            (user_id, market),
        ).fetchall()