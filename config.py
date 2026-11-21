"""
همه‌ی تنظیمات و کلیدهای سرور LUX اینجاست.
اگر در Railway (بخش Variables) متغیری با همین نام بگذاری، آن بر مقدار این فایل غلبه می‌کند.
مقدارهایی که هنوز PASTE_ دارند باید پر شوند.
"""
import os


def _g(name: str, default: str) -> str:
    return os.environ.get(name) or default


# دیتابیس Turso (مثل libsql://xxxx.turso.io)
TURSO_URL = _g("TURSO_URL", "libsql://luxmain-lux101.aws-ap-northeast-1.turso.io")
TURSO_TOKEN = _g("TURSO_TOKEN", "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3OTUyMTIxNTAsImlkIjoiMDFhMWZhZmItNWEwMS03ZjZlLTkwYjYtY2ZjZTdiODJiNmQ3Iiwia2lkIjoiM1FSdi1WU2dTdkJtWlprYm9NMU9qamdXcm9FNGd6Si12LXBBdFFHdFdtTSIsInJpZCI6ImRmY2VmYjQwLTFjMWYtNDk3Zi1iNTA4LTQxYjBhMGQ3MWQ5NiJ9.uJb3LC_QrdhvM3p9lkkuGSubAM_1kbShZIvrB40iVH-fueXqSQapPSfIcxGJ9ZneAu6p4MTElvNc4tURyHIgBw")

# کلید امضای نشست‌ها؛ با تعویض حساب Railway باید همین بماند، وگرنه همه از حساب بیرون می‌افتند.
SESSION_SECRET = _g("SESSION_SECRET", "USphcFFH3H_8HM5vowXnO672EP1XygiCX6wtjbKBBMlGQb6sfpMw3KUTtGH9GYv2")

# ربات مدیریت تلگرام
TELEGRAM_BOT_TOKEN = _g("TELEGRAM_BOT_TOKEN", "9224965119:AAG-DzyJ7VsXT_T0sBmAuLkMtc5JnN1yucw")
ADMIN_TELEGRAM_ID = _g("ADMIN_TELEGRAM_ID", "8355972109")

# رهگشا (مرحله‌ی بعد)
GEMINI_API_KEY = _g("GEMINI_API_KEY", "AQ.Ab8RN6KrVsxbQhRLJnsqR6iUaWRSlRi8b7Lj8C5tgbI0zzmXPw")
GEMINI_MODEL = _g("GEMINI_MODEL", "gemini-flash-latest")
AI_DAILY_LIMIT = int(_g("AI_DAILY_LIMIT", "60"))

# سرویس هوش مصنوعیِ جایگزین (هر سرویسی که با فرمتِ OpenAI کار کند، مثل Groq یا OpenRouter).
# اگر کلیدِ Gemini کار نکند یا شلوغ باشد، رهگشا خودکار از این استفاده می‌کند.
ALT_AI_KEY = _g("ALT_AI_KEY", "PASTE_ALT_AI_KEY")
ALT_AI_URL = _g("ALT_AI_URL", "https://api.groq.com/openai/v1/chat/completions")
ALT_AI_MODEL = _g("ALT_AI_MODEL", "llama-3.3-70b-versatile")

SESSION_DAYS = 180
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024


def is_set(v: str) -> bool:
    return bool(v) and not v.startswith("PASTE_")
