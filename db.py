"""کلاینت ساده‌ی Turso از راه HTTP (بدون وابستگی اضافه)."""
import httpx

import config

_client: httpx.AsyncClient | None = None


def _base() -> str:
    u = config.TURSO_URL.strip()
    if u.startswith("libsql://"):
        u = "https://" + u[len("libsql://"):]
    return u.rstrip("/")


def _arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _cell(c):
    t = c.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(c["value"])
    if t == "float":
        return float(c["value"])
    return c.get("value")


async def _post(requests: list) -> list:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30)
    body = {"requests": requests + [{"type": "close"}]}
    r = await _client.post(
        _base() + "/v2/pipeline",
        json=body,
        headers={"Authorization": "Bearer " + config.TURSO_TOKEN},
    )
    r.raise_for_status()
    results = r.json()["results"]
    out = []
    for res in results[: len(requests)]:
        if res.get("type") == "error":
            raise RuntimeError(res["error"].get("message", "turso error"))
        out.append(res["response"]["result"])
    return out


async def q(sql: str, args: tuple = ()) -> list[dict]:
    """اجرای یک دستور و برگرداندنِ ردیف‌ها به شکل dict."""
    res = (await _post([{"type": "execute", "stmt": {"sql": sql, "args": [_arg(a) for a in args]}}]))[0]
    cols = [c["name"] for c in res.get("cols", [])]
    return [dict(zip(cols, [_cell(c) for c in row])) for row in res.get("rows", [])]


async def x(sql: str, args: tuple = ()) -> int | None:
    """اجرای دستورِ نوشتن؛ آخرین شناسه‌ی درج‌شده را برمی‌گرداند."""
    res = (await _post([{"type": "execute", "stmt": {"sql": sql, "args": [_arg(a) for a in args]}}]))[0]
    rid = res.get("last_insert_rowid")
    return int(rid) if rid is not None else None


async def batch(statements: list[str]) -> None:
    await _post([{"type": "execute", "stmt": {"sql": s}} for s in statements])


SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        uid INTEGER PRIMARY KEY AUTOINCREMENT,
        login_id TEXT UNIQUE NOT NULL,
        display_id TEXT NOT NULL,
        pw_hash TEXT NOT NULL,
        link_key TEXT UNIQUE NOT NULL,
        created_at INTEGER NOT NULL,
        last_login INTEGER,
        last_ip TEXT,
        consent_at INTEGER,
        banned INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS forgot_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER,
        login_id TEXT NOT NULL,
        contact TEXT,
        poll_key TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at INTEGER NOT NULL,
        decided_at INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER NOT NULL,
        kind TEXT NOT NULL,
        detail TEXT,
        at INTEGER NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_events_uid ON events(uid, at)",
    """CREATE TABLE IF NOT EXISTS ai_usage (
        uid INTEGER NOT NULL,
        day TEXT NOT NULL,
        n INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (uid, day)
    )""",
    """CREATE TABLE IF NOT EXISTS ai_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER NOT NULL,
        at INTEGER NOT NULL,
        role TEXT NOT NULL,
        text TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ai_messages_uid ON ai_messages(uid, at)",
    """CREATE TABLE IF NOT EXISTS snapshots (
        uid INTEGER PRIMARY KEY,
        data TEXT NOT NULL,
        size INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )""",
]


async def init() -> None:
    await batch(SCHEMA)
