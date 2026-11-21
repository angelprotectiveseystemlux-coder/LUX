import base64
import hashlib
import hmac
import json
import os
import re
import time

import config

_ID_RE = re.compile(r"^[A-Za-z0-9_]{4,20}$")


def valid_id(s: str) -> bool:
    return bool(_ID_RE.match(s or ""))


def valid_password(p: str) -> bool:
    if not p or len(p) > 64:
        return False
    return (
        len(re.findall(r"[A-Z]", p)) >= 1
        and len(re.findall(r"\d", p)) >= 2
        and len(re.findall(r"[a-z]", p)) >= 4
    )


def hash_password(p: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(p.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "s1$" + salt.hex() + "$" + h.hex()


def check_password(p: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(p.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


def _sign(payload: str) -> str:
    return hmac.new(config.SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(uid: int) -> str:
    body = {"u": uid, "e": int(time.time()) + config.SESSION_DAYS * 86400}
    p = base64.urlsafe_b64encode(json.dumps(body).encode()).decode().rstrip("=")
    return p + "." + _sign(p)


def read_token(tok: str) -> int | None:
    try:
        p, sig = tok.split(".")
        if not hmac.compare_digest(sig, _sign(p)):
            return None
        body = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
        if body["e"] < time.time():
            return None
        return int(body["u"])
    except Exception:
        return None


def random_key(n: int = 30) -> str:
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


# جلوگیری از حدس زدن رمز: ۵ تلاش ناموفق = ۱۰ دقیقه قفل
_fails: dict[str, list[float]] = {}


def locked(key: str) -> bool:
    now = time.time()
    arr = [t for t in _fails.get(key, []) if now - t < 600]
    _fails[key] = arr
    return len(arr) >= 5


def fail(key: str) -> None:
    _fails.setdefault(key, []).append(time.time())


def clear_fail(key: str) -> None:
    _fails.pop(key, None)
