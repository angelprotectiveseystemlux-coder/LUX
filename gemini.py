"""اتصال به Gemini. کلید فقط روی سرور است."""
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


async def _pick_model() -> str:
    """اگر اسم مدل در تنظیمات دیگر وجود نداشت، یک مدل flash مناسب پیدا می‌کند."""
    r = await _http().get(f"{_BASE}/models", params={"pageSize": 200}, headers={"x-goog-api-key": config.GEMINI_API_KEY})
    r.raise_for_status()
    names = []
    for m in r.json().get("models", []):
        n = m.get("name", "").removeprefix("models/")
        if "flash" not in n or any(x in n for x in ("lite", "image", "tts", "live", "audio", "thinking", "exp")):
            continue
        if "generateContent" in m.get("supportedGenerationMethods", []):
            names.append(n)
    if not names:
        raise GeminiError("no_model", "مدلی برای رهگشا پیدا نشد.")
    names.sort(reverse=True)
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
    return await _http().post(
        f"{_BASE}/models/{model}:generateContent",
        json=body,
        headers={"x-goog-api-key": config.GEMINI_API_KEY},
    )


async def chat(system: str, messages: list[dict], max_tokens: int = 1200) -> str:
    global _model
    if not config.is_set(config.GEMINI_API_KEY):
        raise GeminiError("not_configured", "رهگشا هنوز راه‌اندازی نشده.")
    model = _model or config.GEMINI_MODEL
    r = await _generate(model, system, messages, max_tokens)
    if r.status_code == 404:
        _model = await _pick_model()
        r = await _generate(_model, system, messages, max_tokens)
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
