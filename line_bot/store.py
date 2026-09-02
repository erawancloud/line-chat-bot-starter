"""The database, and the two tables this bot keeps.

Plain psycopg rather than an ORM: there are two tables, one of them is a
key-value row, and a migration tool would be more machinery than the thing it
migrates. `CREATE TABLE IF NOT EXISTS` is what makes a redeploy safe.

**The first boot has no database and that is correct.** On Erawan an add-on is
attached *after* the app exists, so `DATABASE_URL` is missing by construction on
the very first release — every read here answers "not configured" instead of
raising, and the admin page says so in words.
"""

from __future__ import annotations

import os

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL", "")

KEYS = ("line_channel_token", "line_channel_secret", "gemini_api_key", "system_prompt")

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant for a small Thai business. "
    "Answer briefly, in the language the customer used."
)


def connect() -> psycopg.Connection:
    if not DATABASE_URL:
        raise RuntimeError("No DATABASE_URL. Attach it: erawan addon add <app> postgres")
    return psycopg.connect(DATABASE_URL)


def ready() -> bool:
    """Whether the database is actually reachable — not whether a variable is set.

    `bool(DATABASE_URL)` is true from the moment the add-on is attached and
    stays true after the database has gone away. This opens a connection, so a
    green answer means the one thing this bot cannot work without is there.
    """
    if not DATABASE_URL:
        return False
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 — a probe reports, it does not raise
        return False


def prepare() -> None:
    if not DATABASE_URL:
        return
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS config ("
                " key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS messages ("
                " id BIGSERIAL PRIMARY KEY,"
                " line_user_id TEXT NOT NULL,"
                " role TEXT NOT NULL,"
                " body TEXT NOT NULL,"
                " at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS messages_user_at"
                " ON messages (line_user_id, at DESC)"
            )
    except Exception:  # noqa: BLE001 — see the module docstring
        pass


def config() -> dict[str, str]:
    if not DATABASE_URL:
        return {}
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT key, value FROM config")
            return dict(cur.fetchall())
    except Exception:  # noqa: BLE001
        return {}


def save(values: dict[str, str]) -> None:
    """Only what was typed. A blank field keeps what is already stored, so
    somebody editing the system prompt does not have to paste three keys again."""
    values = {k: v for k, v in values.items() if k in KEYS and v.strip()}
    if not values:
        return
    with connect() as conn, conn.cursor() as cur:
        for key, value in values.items():
            cur.execute(
                "INSERT INTO config (key, value) VALUES (%s, %s)"
                " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, value.strip()),
            )


def history(line_user_id: str, limit: int = 10) -> list[tuple[str, str]]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT role, body FROM messages WHERE line_user_id = %s"
            " ORDER BY at DESC LIMIT %s",
            (line_user_id, limit),
        )
        return list(reversed(cur.fetchall()))


def remember(line_user_id: str, role: str, body: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO messages (line_user_id, role, body) VALUES (%s, %s, %s)",
            (line_user_id, role, body),
        )


def recent(limit: int = 30) -> list[tuple[str, str, str, str]]:
    if not DATABASE_URL:
        return []
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT line_user_id, role, body, at FROM messages"
                " ORDER BY at DESC LIMIT %s",
                (limit,),
            )
            return [
                (u[:8] + "…", r, b[:160], a.strftime("%d/%m %H:%M"))
                for u, r, b, a in cur.fetchall()
            ]
    except Exception:  # noqa: BLE001
        return []


def mask(value: str) -> str:
    """Enough to recognise which key is set, never enough to use it."""
    if not value:
        return ""
    return f"{value[:4]}…{value[-4:]}" if len(value) > 12 else "set"
