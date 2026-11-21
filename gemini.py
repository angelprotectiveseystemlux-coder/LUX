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


async def _try(model: str, system: str, messages: list[dict], max_tokens: int) -> httpx.Response:
    """اگر گوگل شلوغ بود (۵xx) تا سه بار با وقفه دوباره می‌فرستد."""
    r = await _generate(model, system, messages, max_tokens)
    for i in range(2):
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
    if r.status_code in (401, 404) or (r.status_code == 400 and "model" in r.text.lower()):
        # اسم مدل یا روشِ احراز را از فهرستِ گوگل دوباره پیدا کن و یک‌بار تلاش کن
        _model = await _pick_model()
        r = await _try(_model, system, messages, max_tokens)
    if r.status_code in _BUSY:
        # مدلِ فعلی شلوغ است؛ مدل‌های دیگرِ همان کلید را امتحان کن
        lr = await _list_models()
        if lr.status_code == 200:
            for n in _flash_names(lr.json())[:3]:
                if n == model or n == _model:
                    continue
                r2 = await _try(n, system, messages, max_tokens)
                if r2.status_code == 200:
                    _model = n
                    r = r2
                    break
                r = r2
    if r.status_code in _BUSY:
        raise GeminiError("busy", "رهگشا الان شلوغ است؛ چند لحظه بعد دوباره بفرست.", r.text[:200])
    if r.status_code == 429:
        raise GeminiError("quota", "سهمیه‌ی رهگشا فعلاً تمام شده.", r.text[:300])
    if r.status_code in (400, 401, 403):
        raise GeminiError("ai_key", "کلید رهگشا مشکل دارد.", r.text[:300])
    r.raise_for_status()
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        return "نمی‌توانم به این یکی جواب بدهم. یه چیز دیگه بپرس 🙂"
    parts = cands[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    return text or "…"


async def diagnose() -> str:
    """گزارشِ کوتاه برای مدیر: کلید، فهرست مدل‌ها، و یک تماسِ آزمایشی."""
    k = config.GEMINI_API_KEY
    lines = ["کلید: %s… طول %d، آخرش …%s" % (k[:3], len(k), k[-4:])]
    h = await _http().get(f"{_BASE}/models", params={"pageSize": 1}, headers={"x-goog-api-key": k})
    q = await _http().get(f"{_BASE}/models", params={"pageSize": 1, "key": k})
    lines.append("با هدر: HTTP %s | با ?key=: HTTP %s" % (h.status_code, q.status_code))
    r = await _list_models()
    lines.append("فهرست مدل‌ها: HTTP %s" % r.status_code)
    if r.status_code != 200:
        lines.append(r.text[:300])
        return "\n".join(lines)
    names = _flash_names(r.json())
    lines.append("مدل‌های flash: " + (", ".join(names[:6]) or "هیچ"))
    try:
        t = await chat("فقط یک کلمه جواب بده.", [{"role": "user", "text": "سلام"}], 50)
        lines.append("✅ جواب: " + t[:100])
    except GeminiError as e:
        lines.append("❌ %s %s" % (e.code, e.detail[:300]))
    return "\n".join(lines)
