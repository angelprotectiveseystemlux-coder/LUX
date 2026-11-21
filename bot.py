"""ربات مدیریت تلگرام. فقط به شناسه‌ی عددیِ ADMIN_TELEGRAM_ID جواب می‌دهد."""
import asyncio
import html
import json
import time

import httpx

import config
import db
import gemini

_client: httpx.AsyncClient | None = None


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def _admin() -> int:
    return int(config.ADMIN_TELEGRAM_ID)


async def _call(method: str, **payload):
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=70)
    r = await _client.post(_api(method), json=payload)
    return r.json()


async def send(text: str, markup=None):
    p = {"chat_id": _admin(), "text": text[:4000], "parse_mode": "HTML"}
    if markup:
        p["reply_markup"] = markup
    return await _call("sendMessage", **p)


async def notify(text: str):
    if not (config.is_set(config.TELEGRAM_BOT_TOKEN) and config.is_set(config.ADMIN_TELEGRAM_ID)):
        return
    try:
        await send(text)
    except Exception as e:
        print("notify error:", e)


async def notify_forgot(rid: int, login_id: str, contact: str, note: str):
    if not (config.is_set(config.TELEGRAM_BOT_TOKEN) and config.is_set(config.ADMIN_TELEGRAM_ID)):
        return
    markup = {"inline_keyboard": [[
        {"text": "✅ تأیید", "callback_data": f"fg:ok:{rid}"},
        {"text": "❌ رد", "callback_data": f"fg:no:{rid}"},
    ]]}
    try:
        await send(
            f"🔑 درخواست فراموشی رمز #{rid}\nآیدی: <b>{esc(login_id)}</b>{esc(note)}\nراه تماس: {esc(contact) or '—'}",
            markup,
        )
    except Exception as e:
        print("notify_forgot error:", e)


def fmt(ts) -> str:
    if not ts:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(ts))) + " UTC"


async def _find_user(arg: str):
    if arg.isdigit():
        rows = await db.q("SELECT * FROM users WHERE uid=?", (int(arg),))
    else:
        rows = await db.q("SELECT * FROM users WHERE login_id=?", (arg.lower(),))
    return rows[0] if rows else None


async def _cmd_help():
    await send(
        "دستورها:\n"
        "/stats — آمار کلی\n"
        "/users — فهرست کاربران\n"
        "/user &lt;شناسه یا آیدی&gt; — جزئیات یک کاربر\n"
        "/data &lt;شناسه یا آیدی&gt; — فایل JSON کامل کاربر\n"
        "/top — پرکاربردترین قابلیت‌ها\n"
        "/ai — تست اتصال رهگشا (Gemini)\n"
        "/chats &lt;شناسه یا آیدی&gt; — آخرین گفتگوهای کاربر با رهگشا\n"
        "/forgots — درخواست‌های فراموشی رمز\n"
        "/ban &lt;شناسه&gt; و /unban &lt;شناسه&gt;"
    )


async def _cmd_stats():
    u = (await db.q("SELECT COUNT(*) AS n FROM users"))[0]["n"]
    d = (await db.q("SELECT COUNT(*) AS n FROM users WHERE last_login > ?", (int(time.time()) - 86400,)))[0]["n"]
    s = (await db.q("SELECT COUNT(*) AS n, COALESCE(SUM(size),0) AS b FROM snapshots"))[0]
    f = (await db.q("SELECT COUNT(*) AS n FROM forgot_requests WHERE status='pending'"))[0]["n"]
    await send(
        f"👥 کاربران: {u}\n🟢 فعال در ۲۴ ساعت: {d}\n"
        f"💾 پشتیبان‌ها: {s['n']} ({round(s['b'] / 1024)} KB)\n🔑 فراموشی در انتظار: {f}"
    )


async def _cmd_users():
    rows = await db.q("SELECT uid, display_id, created_at, last_login, banned FROM users ORDER BY uid DESC LIMIT 40")
    if not rows:
        return await send("هنوز کاربری نیست.")
    lines = [
        f"#{r['uid']} <b>{esc(r['display_id'])}</b> — آخرین ورود {fmt(r['last_login'])}{' 🚫' if r['banned'] else ''}"
        for r in rows
    ]
    await send("\n".join(lines))


async def _cmd_user(arg: str):
    u = await _find_user(arg)
    if not u:
        return await send("کاربر پیدا نشد.")
    ev = (await db.q("SELECT COUNT(*) AS n FROM events WHERE uid=?", (u["uid"],)))[0]["n"]
    top = await db.q(
        "SELECT kind, COUNT(*) AS n FROM events WHERE uid=? GROUP BY kind ORDER BY n DESC LIMIT 5", (u["uid"],)
    )
    snap = await db.q("SELECT size, updated_at FROM snapshots WHERE uid=?", (u["uid"],))
    tl = "\n".join(f"  • {esc(t['kind'])}: {t['n']}" for t in top) or "  —"
    await send(
        f"👤 <b>{esc(u['display_id'])}</b> (شناسه {u['uid']})\n"
        f"ساخت حساب: {fmt(u['created_at'])}\nآخرین ورود: {fmt(u['last_login'])}\n"
        f"آی‌پی آخر: {esc(u['last_ip'])}\nپذیرش متن حریم خصوصی: {fmt(u['consent_at'])}\n"
        f"پشتیبان: {(str(round(snap[0]['size'] / 1024)) + ' KB، ' + fmt(snap[0]['updated_at'])) if snap else '—'}\n"
        f"رویدادها: {ev}\nبیشتر استفاده‌شده:\n{tl}"
    )


async def _cmd_data(arg: str):
    u = await _find_user(arg)
    if not u:
        return await send("کاربر پیدا نشد.")
    rows = await db.q("SELECT data FROM snapshots WHERE uid=?", (u["uid"],))
    if not rows:
        return await send("این کاربر هنوز پشتیبانی نفرستاده.")
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=70)
    files = {"document": (f"lux_{u['login_id']}.json", rows[0]["data"].encode("utf-8"), "application/json")}
    await _client.post(_api("sendDocument"), data={"chat_id": _admin()}, files=files)


async def _cmd_chats(arg: str):
    u = await _find_user(arg)
    if not u:
        return await send("کاربر پیدا نشد.")
    rows = await db.q("SELECT at, role, text FROM ai_messages WHERE uid=? ORDER BY id DESC LIMIT 20", (u["uid"],))
    if not rows:
        return await send("گفتگویی نیست.")
    lines = [f"{'🧑' if r['role'] == 'user' else '🤖'} {esc(r['text'])[:300]}" for r in reversed(rows)]
    await send("\n\n".join(lines))


async def _cmd_ai():
    try:
        t = await gemini.chat("فقط یک کلمه جواب بده.", [{"role": "user", "text": "سلام"}], 50)
        await send("✅ Gemini جواب داد: " + esc(t[:200]))
    except gemini.GeminiError as e:
        await send(f"❌ {esc(e.code)}: {esc(e.message)}\n{esc(e.detail)}")
    except Exception as e:
        await send("❌ " + esc(type(e).__name__) + ": " + esc(str(e)[:300]))


async def _cmd_top():
    rows = await db.q("SELECT kind, COUNT(*) AS n FROM events GROUP BY kind ORDER BY n DESC LIMIT 15")
    if not rows:
        return await send("هنوز رویدادی ثبت نشده.")
    await send("\n".join(f"{i + 1}. {esc(r['kind'])} — {r['n']}" for i, r in enumerate(rows)))


async def _cmd_forgots():
    rows = await db.q("SELECT * FROM forgot_requests WHERE status='pending' ORDER BY id DESC LIMIT 10")
    if not rows:
        return await send("درخواست بازی نیست.")
    for r in rows:
        await notify_forgot(r["id"], r["login_id"], r["contact"] or "", "")


async def _handle_callback(cb: dict):
    data = cb.get("data", "")
    if data.startswith("fg:"):
        _, act, rid = data.split(":")
        status = "approved" if act == "ok" else "denied"
        await db.x("UPDATE forgot_requests SET status=?, decided_at=? WHERE id=? AND status='pending'", (status, int(time.time()), int(rid)))
        await _call("answerCallbackQuery", callback_query_id=cb["id"], text="ثبت شد")
        await send(("✅ تأیید شد" if act == "ok" else "❌ رد شد") + f" — درخواست #{rid}")


async def _handle_message(m: dict):
    text = (m.get("text") or "").strip()
    if not text.startswith("/"):
        return
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    arg = arg.strip()
    if cmd in ("/start", "/help"):
        await _cmd_help()
    elif cmd == "/stats":
        await _cmd_stats()
    elif cmd == "/users":
        await _cmd_users()
    elif cmd == "/user" and arg:
        await _cmd_user(arg)
    elif cmd == "/data" and arg:
        await _cmd_data(arg)
    elif cmd == "/ai":
        await _cmd_ai()
    elif cmd == "/chats" and arg:
        await _cmd_chats(arg)
    elif cmd == "/top":
        await _cmd_top()
    elif cmd == "/forgots":
        await _cmd_forgots()
    elif cmd in ("/ban", "/unban") and arg.isdigit():
        await db.x("UPDATE users SET banned=? WHERE uid=?", (1 if cmd == "/ban" else 0, int(arg)))
        await send("انجام شد.")
    else:
        await send("دستور نامعتبر. /help")


async def run():
    offset = 0
    print("telegram bot started")
    while True:
        try:
            res = await _call("getUpdates", offset=offset, timeout=50, allowed_updates=["message", "callback_query"])
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message")
                cb = upd.get("callback_query")
                sender = (msg or cb or {}).get("from", {}).get("id")
                if sender != _admin():
                    continue  # هر کس دیگری: نادیده
                try:
                    if msg:
                        await _handle_message(msg)
                    elif cb:
                        await _handle_callback(cb)
                except Exception as e:
                    await send("خطا: " + esc(e))
        except asyncio.CancelledError:
            return
        except Exception as e:
            print("bot loop error:", e)
            await asyncio.sleep(5)
