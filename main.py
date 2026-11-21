import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

import bot
import config
import db
import gemini
import security as sec


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    try:
        if config.is_set(config.TURSO_URL):
            await db.init()
        if config.is_set(config.TELEGRAM_BOT_TOKEN) and config.is_set(config.ADMIN_TELEGRAM_ID):
            task = asyncio.create_task(bot.run())
    except Exception as e:  # سرور بالا بیاید تا بشود خطا را دید
        print("startup error:", e)
    yield
    if task:
        task.cancel()


app = FastAPI(lifespan=lifespan)


def now() -> int:
    return int(time.time())


def ip_of(req: Request) -> str:
    fwd = req.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return req.client.host if req.client else ""


def err(code: str, msg: str, status: int = 400):
    return JSONResponse({"ok": False, "code": code, "message": msg}, status_code=status)


async def current_user(authorization: str = Header(default="")) -> dict:
    tok = authorization.removeprefix("Bearer ").strip()
    uid = sec.read_token(tok)
    if uid is None:
        raise HTTPException(401, "نشست معتبر نیست")
    rows = await db.q("SELECT * FROM users WHERE uid=?", (uid,))
    if not rows or rows[0]["banned"]:
        raise HTTPException(401, "حساب فعال نیست")
    return rows[0]


def session_payload(u: dict) -> dict:
    return {
        "ok": True,
        "token": sec.make_token(u["uid"]),
        "uid": u["uid"],
        "id": u["display_id"],
        "link": u["link_key"],
        "consent": u["consent_at"] is not None,
    }


@app.get("/")
@app.get("/health")
async def health():
    return {"ok": True, "service": "lux", "time": now()}


@app.post("/auth/check")
async def check_id(body: dict):
    i = str(body.get("id", "")).strip()
    if not sec.valid_id(i):
        return err("bad_id", "آیدی باید ۴ تا ۲۰ حرف انگلیسی، عدد یا زیرخط باشد.")
    rows = await db.q("SELECT 1 FROM users WHERE login_id=?", (i.lower(),))
    return {"ok": True, "available": not rows}


@app.post("/auth/register")
async def register(body: dict, req: Request):
    i = str(body.get("id", "")).strip()
    pw = str(body.get("password", ""))
    if not sec.valid_id(i):
        return err("bad_id", "آیدی باید ۴ تا ۲۰ حرف انگلیسی، عدد یا زیرخط باشد.")
    if not sec.valid_password(pw):
        return err("bad_password", "رمز باید حداقل ۱ حرف بزرگ، ۲ عدد و ۴ حرف کوچک داشته باشد.")
    if await db.q("SELECT 1 FROM users WHERE login_id=?", (i.lower(),)):
        return err("taken", "این آیدی قبلاً گرفته شده.", 409)
    h = await asyncio.to_thread(sec.hash_password, pw)
    try:
        uid = await db.x(
            "INSERT INTO users(login_id,display_id,pw_hash,link_key,created_at,last_login,last_ip) VALUES(?,?,?,?,?,?,?)",
            (i.lower(), i, h, sec.random_key(), now(), now(), ip_of(req)),
        )
    except Exception:
        return err("taken", "این آیدی قبلاً گرفته شده.", 409)
    u = (await db.q("SELECT * FROM users WHERE uid=?", (uid,)))[0]
    await bot.notify(f"🆕 کاربر جدید: <b>{bot.esc(u['display_id'])}</b> (شناسه {uid})")
    return session_payload(u)


@app.post("/auth/login")
async def login(body: dict, req: Request):
    i = str(body.get("id", "")).strip().lower()
    pw = str(body.get("password", ""))
    key = i + "|" + ip_of(req)
    if sec.locked(key):
        return err("locked", "چند بار رمز اشتباه زده شد. ۱۰ دقیقه بعد دوباره امتحان کن.", 429)
    rows = await db.q("SELECT * FROM users WHERE login_id=?", (i,))
    ok = bool(rows) and await asyncio.to_thread(sec.check_password, pw, rows[0]["pw_hash"])
    if not ok:
        sec.fail(key)
        return err("bad_login", "آیدی یا رمز درست نیست.", 401)
    u = rows[0]
    if u["banned"]:
        return err("banned", "این حساب غیرفعال است.", 403)
    sec.clear_fail(key)
    await db.x("UPDATE users SET last_login=?, last_ip=? WHERE uid=?", (now(), ip_of(req), u["uid"]))
    return session_payload(u)


@app.post("/auth/json-login")
async def json_login(body: dict, req: Request):
    link = str(body.get("link", "")).strip()
    if len(link) < 20:
        return {"ok": True, "found": False}
    rows = await db.q("SELECT * FROM users WHERE link_key=?", (link,))
    if not rows or rows[0]["banned"]:
        return {"ok": True, "found": False}
    u = rows[0]
    await db.x("UPDATE users SET last_login=?, last_ip=? WHERE uid=?", (now(), ip_of(req), u["uid"]))
    out = session_payload(u)
    out["found"] = True
    return out


@app.post("/auth/forgot")
async def forgot(body: dict):
    i = str(body.get("id", "")).strip()
    contact = str(body.get("contact", "")).strip()[:120]
    rows = await db.q("SELECT uid, display_id FROM users WHERE login_id=?", (i.lower(),))
    poll = sec.random_key(20)
    uid = rows[0]["uid"] if rows else None
    rid = await db.x(
        "INSERT INTO forgot_requests(uid,login_id,contact,poll_key,created_at) VALUES(?,?,?,?,?)",
        (uid, i.lower()[:40], contact, poll, now()),
    )
    note = "" if rows else " (این آیدی در سیستم نیست)"
    await bot.notify_forgot(rid, i, contact, note)
    # عمداً درباره‌ی وجود یا نبودن آیدی چیزی لو نمی‌دهیم
    return {"ok": True, "request_id": rid, "poll_key": poll}


@app.post("/auth/forgot/status")
async def forgot_status(body: dict):
    rows = await db.q(
        "SELECT status FROM forgot_requests WHERE id=? AND poll_key=?",
        (int(body.get("request_id", 0)), str(body.get("poll_key", ""))),
    )
    if not rows:
        return err("not_found", "درخواست پیدا نشد.", 404)
    return {"ok": True, "status": rows[0]["status"]}


@app.post("/auth/reset")
async def reset(body: dict):
    pw = str(body.get("password", ""))
    if not sec.valid_password(pw):
        return err("bad_password", "رمز باید حداقل ۱ حرف بزرگ، ۲ عدد و ۴ حرف کوچک داشته باشد.")
    rows = await db.q(
        "SELECT * FROM forgot_requests WHERE id=? AND poll_key=? AND status='approved'",
        (int(body.get("request_id", 0)), str(body.get("poll_key", ""))),
    )
    if not rows or rows[0]["uid"] is None:
        return err("not_approved", "این درخواست هنوز تأیید نشده.", 403)
    h = await asyncio.to_thread(sec.hash_password, pw)
    await db.x("UPDATE users SET pw_hash=? WHERE uid=?", (h, rows[0]["uid"]))
    await db.x("UPDATE forgot_requests SET status='used' WHERE id=?", (rows[0]["id"],))
    u = (await db.q("SELECT * FROM users WHERE uid=?", (rows[0]["uid"],)))[0]
    return session_payload(u)


@app.get("/me")
async def me(u: dict = Depends(current_user)):
    return session_payload(u)


@app.post("/me/consent")
async def consent(u: dict = Depends(current_user)):
    await db.x("UPDATE users SET consent_at=? WHERE uid=?", (now(), u["uid"]))
    return {"ok": True}


@app.post("/events")
async def events(body: dict, u: dict = Depends(current_user)):
    items = body.get("items", [])[:100]
    for it in items:
        await db.x(
            "INSERT INTO events(uid,kind,detail,at) VALUES(?,?,?,?)",
            (u["uid"], str(it.get("kind", ""))[:40], str(it.get("detail", ""))[:200], int(it.get("at", now()))),
        )
    return {"ok": True, "n": len(items)}


@app.post("/sync/snapshot")
async def put_snapshot(req: Request, u: dict = Depends(current_user)):
    raw = await req.body()
    if len(raw) > config.MAX_SNAPSHOT_BYTES:
        return err("too_big", "فایل پشتیبان بیش از حد بزرگ است.", 413)
    try:
        json.loads(raw)
    except Exception:
        return err("bad_json", "فایل معتبر نیست.")
    await db.x(
        "INSERT INTO snapshots(uid,data,size,updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(uid) DO UPDATE SET data=excluded.data,size=excluded.size,updated_at=excluded.updated_at",
        (u["uid"], raw.decode("utf-8"), len(raw), now()),
    )
    return {"ok": True, "updated_at": now()}


@app.get("/sync/snapshot")
async def get_snapshot(u: dict = Depends(current_user)):
    rows = await db.q("SELECT data, updated_at FROM snapshots WHERE uid=?", (u["uid"],))
    if not rows:
        return {"ok": True, "found": False}
    return {"ok": True, "found": True, "updated_at": rows[0]["updated_at"], "data": rows[0]["data"]}


@app.post("/ai/chat")
async def ai_chat(body: dict, u: dict = Depends(current_user)):
    system = str(body.get("system", ""))[:12000]
    msgs = body.get("messages", [])[-24:]
    if not msgs:
        return err("empty", "پیامی نیست.")
    day = time.strftime("%Y-%m-%d", time.gmtime())
    used = await db.q("SELECT n FROM ai_usage WHERE uid=? AND day=?", (u["uid"], day))
    if used and used[0]["n"] >= config.AI_DAILY_LIMIT:
        return err("quota", "سهمیه‌ی امروزِ رهگشا تمام شد؛ فردا برمی‌گردد.", 429)
    try:
        text = await gemini.chat(system, msgs)
    except gemini.GeminiError as e:
        return err(e.code, e.message, 429 if e.code == "quota" else 503)
    except Exception:
        return err("ai_down", "رهگشا فعلاً جواب نمی‌دهد.", 503)
    await db.x(
        "INSERT INTO ai_usage(uid,day,n) VALUES(?,?,1) ON CONFLICT(uid,day) DO UPDATE SET n=n+1",
        (u["uid"], day),
    )
    t = now()
    last = msgs[-1]
    if last.get("role") == "user" and not body.get("proactive"):
        await db.x("INSERT INTO ai_messages(uid,at,role,text) VALUES(?,?,?,?)", (u["uid"], t, "user", str(last.get("text", ""))[:4000]))
    await db.x("INSERT INTO ai_messages(uid,at,role,text) VALUES(?,?,?,?)", (u["uid"], t, "ai", text[:4000]))
    return {"ok": True, "text": text}
