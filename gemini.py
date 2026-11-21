"""اتصال به Gemini. کلید فقط روی سرور است."""
import asyncio
import re

import httpx

import config

_BASE = "https://generativelanguage.googleapis.com/v1beta"
_client: httpx.AsyncClient | None = None
_model: str | None = None


class GeminiError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=35)
    return _client


def _ver(name: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


async def _req(method: str, url: str, params: dict | None = None, json: dict | None = None) -> httpx.Response:
    """اول با هدر x-goog-api-key؛ اگر ۴۰۱ شد یک‌بار با ?key= امتحان می‌کند."""
    r = await _http().request(method, url, params=params, json=json, headers={"x-goog-api-key": config.GEMINI_API_KEY})
    if r.status_code == 401:
        p = dict(params or {})
        p["key"] = config.GEMINI_API_KEY
        r2 = await _http().request(method, url, params=p, json=json)
        if r2.status_code != 401:
            return r2
    return r


async def _list_models() -> httpx.Response:
    return await _req("GET", f"{_BASE}/models", params={"pageSize": 200})


def _flash_names(data: dict) -> list[str]:
    names = []
    for m in data.get("models", []):
        n = m.get("name", "").removeprefix("models/")
        if "flash" not in n or n.endswith("-latest"):
            continue
        if any(x in n for x in ("lite", "image", "tts", "live", "audio", "thinking", "exp", "preview")):
            continue
        if "generateContent" in m.get("supportedGenerationMethods", []):
            names.append(n)
    names.sort(key=_ver, reverse=True)
    return names


async def _pick_model() -> str:
    """مدلِ flashِ مناسب را از فهرستِ خودِ گوگل پیدا می‌کند."""
    r = await _list_models()
    if r.status_code in (400, 401, 403):
        raise GeminiError("ai_key", "کلید رهگشا مشکل دارد.", "فهرست مدل‌ها HTTP %s: %s" % (r.status_code, r.text[:300]))
    r.raise_for_status()
    names = _flash_names(r.json())
    if not names:
        raise GeminiError("no_model", "مدلی برای رهگشا پیدا نشد.")
    return names[0]


async def _generate(model: str, system: str, messages: list[dict], max_tokens: int):
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [
            {"role": "user" if m.get("role") == "user" else "model", "parts": [{"text": str(m.get("text", ""))}]}
            for m in messages
        ],
        "generationConfig": {"temperature": 0.9, "maxOutputTokens": max_tokens},
    }
    return await _req("POST", f"{_BASE}/models/{model}:generateContent", json=body)


_BUSY = (500, 502, 503, 504)

# بعضی کلیدها (مثل AQ.) اجازه‌ی «فهرست مدل‌ها» ندارند؛ در آن حالت از این اسم‌ها امتحان می‌کنیم.
_CANDIDATES = ["gemini-flash-latest", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3-flash", "gemini-2.5-flash"]


async def _names() -> list[str]:
    try:
        r = await _list_models()
        if r.status_code == 200:
            n = _flash_names(r.json())
            if n:
                return n
    except Exception:
        pass
    return list(_CANDIDATES)


async def _try(model: str, system: str, messages: list[dict], max_tokens: int, retries: int = 2) -> httpx.Response:
    """اگر گوگل شلوغ بود (۵xx) با وقفه دوباره می‌فرستد."""
    r = await _generate(model, system, messages, max_tokens)
    for i in range(retries):
        if r.status_code not in _BUSY:
            break
        await asyncio.sleep(1.5 * (i + 1))
        r = await _generate(model, system, messages, max_tokens)
    return r


async def chat(system: str, messages: list[dict], max_tokens: int = 1200) -> str:
    global _model
    if not config.is_set(config.GEMINI_API_KEY):
        raise GeminiError("not_configured", "رهگشا هنوز راه‌اندازی نشده.")
    model = _model or config.GEMINI_MODEL
    r = await _try(model, system, messages, max_tokens)
    bad = r.status_code in (401, 404) or r.status_code in _BUSY or (r.status_code == 400 and "model" in r.text.lower())
    if bad:
        # مدلِ فعلی جواب نداد (نبود یا شلوغ است)؛ چند مدلِ دیگر را امتحان کن
        tried = 0
        for n in await _names():
            if n == model or tried >= 3:
                continue
            tried += 1
            r2 = await _try(n, system, messages, max_tokens, retries=0)
            if r2.status_code == 200:
                _model = n
                r = r2
                break
            if r2.status_code != 404:
                r = r2
    if r.status_code in _BUSY:
        raise GeminiError("busy", "رهگشا الان شلوغ است؛ چند لحظه بعد دوباره بفرست.", r.text[:200])
    if r.status_code == 429:
        raise GeminiError("quota", "سهمیه‌ی رهگشا فعلاً تمام شده.", r.text[:300])
    if r.status_code in (400, 401, 403, 404):
        raise GeminiError("ai_key", "کلید یا مدلِ رهگشا مشکل دارد.", "HTTP %s: %s" % (r.status_code, r.text[:300]))
    r.raise_for_status()
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        return "نمی‌توانم به این یکی جواب بدهم. یه چیز دیگه بپرس 🙂"
    parts = cands[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    return text or "…"


async def diagnose() -> str:
    """گزارشِ کوتاه برای مدیر: کلید، فهرست مدل‌ها (اختیاری)، و تماسِ آزمایشیِ اصلی."""
    k = config.GEMINI_API_KEY
    lines = ["کلید: %s… طول %d، آخرش …%s" % (k[:3], len(k), k[-4:])]
    try:
        r = await _list_models()
        if r.status_code == 200:
            lines.append("فهرست مدل‌ها: " + ", ".join(_flash_names(r.json())[:5]))
        else:
            lines.append("فهرست مدل‌ها: HTTP %s (بعضی کلیدها اجازه‌ی فهرست‌گیری ندارند؛ مهم نتیجه‌ی تماسِ آزمایشی است)" % r.status_code)
    except Exception as e:
        lines.append("فهرست مدل‌ها: %s" % type(e).__name__)
    try:
        t = await chat("فقط یک کلمه جواب بده.", [{"role": "user", "text": "سلام"}], 50)
        lines.append("✅ جواب (مدل %s): %s" % (_model or config.GEMINI_MODEL, t[:100]))
    except GeminiError as e:
        lines.append("❌ %s: %s" % (e.code, e.detail[:300] or e.message))
    except Exception as e:
        lines.append("❌ %s: %s" % (type(e).__name__, str(e)[:200]))
    return "\n".join(lines)
