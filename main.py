"""
SPIDERMAT OTP BOT — optimized Railway build

Required environment:
  BOT_TOKEN          Telegram bot token
  OWNER_ID           Optional Telegram user id for system alerts

Optional environment:
  IVAS_USERNAME      IVAS login username/email for auto-login
  IVAS_PASSWORD      IVAS login password for auto-login
  IVAS_BASE_URL      Default: https://www.ivasms.com
  DEFAULT_TARGET     Default: -1003686221386
  CHANNEL_LINK       Default: https://t.me/matchaappp
  NUMBER_LINK        Default: https://t.me/matchaappp

Runtime files:
  cookie.json
  file/sent_cache.json
  file/groups.json

Install:
  pip install httpx beautifulsoup4 phonenumbers colorama
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

import httpx
import phonenumbers
from bs4 import BeautifulSoup
from colorama import Fore, Style, init
from phonenumbers import geocoder

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
init(autoreset=True)


# ============================================================================
# CONFIGURATION
# ============================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")
except ValueError:
    OWNER_ID = 0

try:
    DEFAULT_TARGET = int(os.getenv("DEFAULT_TARGET", "-1003686221386"))
except ValueError:
    DEFAULT_TARGET = -1003686221386

IVAS_BASE_URL = os.getenv("IVAS_BASE_URL", "https://www.ivasms.com").rstrip("/")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/matchaappp")
NUMBER_LINK = os.getenv("NUMBER_LINK", "https://t.me/matchaappp")

COOKIE_FILE = os.getenv("COOKIE_FILE", "cookie.json")
CACHE_FILE = os.getenv("CACHE_FILE", "file/sent_cache.json")
GROUPS_FILE = os.getenv("GROUPS_FILE", "file/groups.json")

MAX_CACHE = 2_000
MAX_NUMBER_WORKERS = int(os.getenv("MAX_NUMBER_WORKERS", "3"))
MESSAGE_TAG = os.getenv("MESSAGE_TAG", "TG1").strip() or "TG1"

# Jeda internal dibuat minimal. Connection pooling dan batas worker tetap
# mencegah busy-loop yang membuat endpoint mengembalikan 429.
POLL_INTERVAL_MIN = float(os.getenv("POLL_INTERVAL_MIN", "0.05"))
POLL_INTERVAL_MAX = float(os.getenv("POLL_INTERVAL_MAX", "0.10"))
MIN_REQUEST_GAP = 0.05
KEEPALIVE_INTERVAL = 480.0
HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)


# ============================================================================
# LOGGING
# ============================================================================

_LOG_ICONS = {
    "OTP": "🟢",
    "COOKIE": "🍪",
    "CONFIG": "⚙️",
    "WORKER": "🔄",
    "RANGE": "📡",
    "CSRF": "🔑",
    "KA-OK": "💚",
    "KA-WARN": "🟡",
    "KA-ERR": "🔴",
    "KEEPALIVE": "🫀",
    "SERVER": "🌐",
    "CACHE": "💾",
    "TG-ERR": "❌",
    "NUM": "📟",
    "SMS": "📨",
    "THREAD+": "🧵",
    "SHUTDOWN": "🛑",
    "FATAL": "💀",
    "CMD": "⌨️",
    "GROUP": "👥",
    "AUTH": "🔐",
}


def _log(tag: str, message: str, color: str = Fore.CYAN) -> None:
    icon = _LOG_ICONS.get(tag, "•")
    ts = datetime.now().strftime("%H:%M:%S")
    print(
        color + f"  {ts}  {icon} {tag:<9}  {message}" + Style.RESET_ALL,
        flush=True,
    )


def _sleep(seconds: float) -> None:
    """Centralized sleep, kept interruptible and easy to tune."""
    time.sleep(max(0.0, seconds))


# ============================================================================
# GENERAL HELPERS
# ============================================================================


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def code_to_flag(code: str) -> str:
    try:
        return "".join(chr(127397 + ord(char)) for char in code.upper())
    except Exception:
        return "🌐"


def normalize_number(number: str, country_code: str = "") -> str:
    value = re.sub(r"[\s().-]", "", str(number)).lstrip("+")
    if value.startswith("0") and country_code:
        return country_code + value[1:]
    return value


def mask_phone(number: str) -> str:
    digits = re.sub(r"\D", "", str(number))
    if len(digits) <= 8:
        return f"+{digits}"
    return f"+{digits[:4]}****{digits[-4:]}"


def detect_country(number: str, fallback: str = "UN") -> tuple[str, str]:
    try:
        parsed = phonenumbers.parse("+" + re.sub(r"\D", "", number), None)
        region = phonenumbers.region_code_for_number(parsed) or fallback
        return region, code_to_flag(region)
    except Exception:
        return fallback, "🌐"


def parse_range(value: str) -> tuple[str, str]:
    country = re.sub(r"\s*\(.*?\)", "", value)
    country = re.sub(r"\d+", "", country)
    country = re.sub(r"\s+", " ", country).strip().upper()
    match = re.search(r"\((\d+)\)", value)
    return country, match.group(1) if match else ""


# ============================================================================
# COOKIE / HTTP SESSION
# ============================================================================


def load_cookies() -> list[dict[str, str]]:
    if not os.path.exists(COOKIE_FILE):
        _log("COOKIE", f"{COOKIE_FILE} tidak ditemukan", Fore.YELLOW)
        return []

    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        _log("COOKIE", f"gagal membaca {COOKIE_FILE}: {exc}", Fore.RED)
        return []

    if not data:
        return []
    if isinstance(data, list):
        if all(
            isinstance(item, dict)
            and "name" in item
            and "value" in item
            for item in data
        ):
            return [{str(item["name"]): str(item["value"]) for item in data}]
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and all(isinstance(value, dict) for value in data.values()):
        return list(data.values())
    if isinstance(data, dict):
        return [data]
    return []


def make_http_client(cookies: dict[str, str] | None = None) -> httpx.Client:
    client = httpx.Client(
        follow_redirects=True,
        timeout=HTTP_TIMEOUT,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": IVAS_BASE_URL,
            "Referer": f"{IVAS_BASE_URL}/",
        },
        limits=httpx.Limits(
            max_connections=8,
            max_keepalive_connections=4,
            keepalive_expiry=30.0,
        ),
    )
    if cookies:
        client.cookies.update(cookies)
    return client


class SessionExpired(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


class PortalBlocked(RuntimeError):
    pass


def is_login_redirect(response: httpx.Response) -> bool:
    location = str(response.url).lower()
    if "/login" in location:
        return True
    content = response.text[:10_000].lower()
    return (
        'action="/login"' in content
        or "please log in" in content
        or "session expired" in content
    )


def is_cloudflare_or_blocked(response: httpx.Response) -> bool:
    if response.status_code in (403, 503):
        return True
    sample = response.text[:3_000].lower()
    markers = (
        "just a moment",
        "challenges.cloudflare.com",
        "cf-browser-verification",
        "temporarily rate limited",
        "error 1015",
        "error 1020",
        "checking your browser",
    )
    return any(marker in sample for marker in markers)


# ============================================================================
# TELEGRAM HTTP CLIENT
# ============================================================================


_tg_client = httpx.Client(
    timeout=httpx.Timeout(connect=8.0, read=45.0, write=10.0, pool=8.0),
    limits=httpx.Limits(max_connections=12, max_keepalive_connections=6),
    headers={"User-Agent": "spidermat-otp-bot/2.0"},
)
_tg_send_lock = threading.Lock()


def _tg_url(method: str) -> str:
    return f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"


def _tg_post(
    method: str,
    payload: dict[str, Any],
    retries: int = 3,
) -> dict[str, Any]:
    for attempt in range(retries):
        try:
            response = _tg_client.post(_tg_url(method), json=payload)
            data = response.json()
            if data.get("ok"):
                return data

            if response.status_code == 429:
                retry_after = float(data.get("parameters", {}).get("retry_after", 1))
                _sleep(min(retry_after + 0.2, 30.0))
                continue

            _log(
                "TG-ERR",
                f"{method}: {data.get('description', 'unknown Telegram error')}",
                Fore.RED,
            )
            return data
        except Exception as exc:
            if attempt + 1 >= retries:
                _log("TG-ERR", f"{method}: {exc}", Fore.RED)
            else:
                _sleep(0.25 * (attempt + 1))
    return {"ok": False}


def tg_send_msg(chat_id: int | str, text: str) -> bool:
    return bool(
        _tg_post(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        ).get("ok")
    )


# ============================================================================
# OTP FORMAT + TELEGRAM BUTTONS
# ============================================================================


SERVICE_PATTERN = re.compile(
    r"(WhatsApp|Telegram|Google|Facebook|Instagram|TikTok|Grab|Gojek|Shopee|Tokopedia)",
    re.IGNORECASE,
)


def detect_service(text: str) -> str:
    match = SERVICE_PATTERN.search(text)
    return match.group(1).upper() if match else "OTP"


OTP_PATTERN = re.compile(r"\b\d{3}[- ]?\d{3}\b|\b\d{4,8}\b")


def extract_otp(text: str) -> str | None:
    match = OTP_PATTERN.search(text)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(0))
    return digits if 4 <= len(digits) <= 8 else None


def country_name_and_language(number: str, region: str, sms_text: str) -> str:
    """Return the screenshot-style second line, e.g. Indonesian or English."""
    if region.upper() == "ID":
        return "Indonesian"

    if re.search(
        r"\b(the|your|code|verify|verification|use|expires|don't|dont|share)\b",
        sms_text,
        re.IGNORECASE,
    ):
        return "English"

    try:
        parsed = phonenumbers.parse("+" + re.sub(r"\D", "", number), None)
        description = geocoder.description_for_number(parsed, "en").strip()
        if description:
            return description
    except Exception:
        pass
    return region or "Unknown"


def normalize_sms_for_display(text: str) -> str:
    """Keep the SMS readable inside Telegram's blockquote."""
    text = text.replace("<#>", "").strip()
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def build_otp_message(
    otp: str,
    flag: str,
    region_code: str,
    number: str,
    sms_text: str,
    country_name: str,
) -> str:
    """
    Match the reference layout:
      line 1: 🌐 TG1 🟢 | +number 📌 prefix | ❯
      line 2: country/language
      line 3: blockquoted SMS body
    """
    del otp, flag  # kept in the signature for compatibility with old callers
    digits = re.sub(r"\D", "", str(number))
    prefix = digits[:6] if len(digits) >= 6 else digits
    body = normalize_sms_for_display(sms_text) or "OTP received"
    return (
        f"🌐 {esc(MESSAGE_TAG)} 🟢 | +{esc(digits)} "
        f"📌 {esc(prefix)} | ❯\n"
        f"{esc(country_name)}\n"
        f"<blockquote>{esc(body)}</blockquote>"
    )


def otp_keyboard(otp: str | None) -> dict[str, Any]:
    # Telegram does not expose native button colors in Bot API. The labels
    # intentionally use the same visual indicators as the reference image.
    primary: dict[str, Any] = {
        "text": f"🔑 📋 {otp}" if otp else "🔑 📋 OTP",
    }
    if otp:
        primary["copy_text"] = {"text": otp}

    return {
        "inline_keyboard": [
            [
                {"text": "🌐 Channel ↗", "url": CHANNEL_LINK},
                primary,
            ],
            [{"text": "📞 Get Number ↗", "url": NUMBER_LINK}],
        ]
    }


def tg_send_otp(otp: str, message: str) -> None:
    targets = list_groups()
    payload_base = {
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": otp_keyboard(otp),
    }

    def send_one(chat_id: int | str) -> None:
        payload = {**payload_base, "chat_id": chat_id}
        _tg_post("sendMessage", payload)

    if len(targets) <= 1:
        for target in targets:
            send_one(target)
        return

    # Target groups are independent; cap fan-out to prevent Telegram bursts.
    with ThreadPoolExecutor(
        max_workers=min(3, len(targets)),
        thread_name_prefix="telegram-send",
    ) as pool:
        list(pool.map(send_one, targets))


# ============================================================================
# CACHE + GROUP TARGETS
# ============================================================================


_sent_cache_lock = threading.Lock()
_cache_dirty = False
_last_cache_save = 0.0


def load_sent_cache() -> set[str]:
    os.makedirs(os.path.dirname(CACHE_FILE) or ".", exist_ok=True)
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return set(data) if isinstance(data, list) else set()
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()


sent_cache = load_sent_cache()


def save_sent_cache_now() -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_FILE) or ".", exist_ok=True)
        with _sent_cache_lock:
            values = list(sent_cache)[-MAX_CACHE:]
        with open(CACHE_FILE, "w", encoding="utf-8") as handle:
            json.dump(values, handle)
    except OSError as exc:
        _log("CACHE", f"save error: {exc}", Fore.YELLOW)


def cache_add(value: str) -> None:
    global _cache_dirty, _last_cache_save
    with _sent_cache_lock:
        sent_cache.add(value)
        if len(sent_cache) > MAX_CACHE:
            sent_cache.difference_update(list(sent_cache)[:-MAX_CACHE])
    _cache_dirty = True
    if time.time() - _last_cache_save >= 5.0:
        save_sent_cache_now()
        _last_cache_save = time.time()
        _cache_dirty = False


_targets_lock = threading.Lock()
_forward_targets: set[int] = {DEFAULT_TARGET}


def _load_groups() -> None:
    try:
        with open(GROUPS_FILE, "r", encoding="utf-8") as handle:
            values = json.load(handle)
        if isinstance(values, list):
            with _targets_lock:
                _forward_targets.update(int(value) for value in values)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return


def _save_groups() -> None:
    try:
        os.makedirs(os.path.dirname(GROUPS_FILE) or ".", exist_ok=True)
        with _targets_lock:
            values = sorted(_forward_targets)
        with open(GROUPS_FILE, "w", encoding="utf-8") as handle:
            json.dump(values, handle)
    except OSError as exc:
        _log("GROUP", f"save error: {exc}", Fore.YELLOW)


def add_group(chat_id: int) -> bool:
    with _targets_lock:
        if chat_id in _forward_targets:
            return False
        _forward_targets.add(chat_id)
    _save_groups()
    return True


def remove_group(chat_id: int) -> bool:
    with _targets_lock:
        if chat_id == DEFAULT_TARGET or chat_id not in _forward_targets:
            return False
        _forward_targets.remove(chat_id)
    _save_groups()
    return True


def list_groups() -> list[int]:
    with _targets_lock:
        return list(_forward_targets)


# System alerts are deduplicated for the whole process.
_system_alert_lock = threading.Lock()
_system_alerts_sent: set[str] = set()


def system_alert_once(key: str, text: str) -> None:
    if not OWNER_ID:
        return
    with _system_alert_lock:
        if key in _system_alerts_sent:
            return
        _system_alerts_sent.add(key)
    tg_send_msg(OWNER_ID, text)


def clear_system_alert(key: str) -> None:
    with _system_alert_lock:
        _system_alerts_sent.discard(key)


# ============================================================================
# IVAS API
# ============================================================================


_RATE_LIMIT_MARKERS = (
    "temporarily rate limited",
    "error 1027",
    "please check back later",
    "has been rate limited",
    "error 1015",
    "you have been blocked",
    "attention required",
    "error 1020",
    "checking your browser",
    "just a moment",
)


def is_rate_limited(response: httpx.Response) -> bool:
    if response.status_code == 429:
        return True
    sample = response.text[:3_000].lower()
    return any(marker in sample for marker in _RATE_LIMIT_MARKERS)


def _recv_headers(base: str) -> dict[str, str]:
    return {
        "Accept": "text/html,*/*;q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": f"{base}/portal/sms/received",
        "Origin": base,
    }


_recv_csrf_cache: dict[int, dict[str, Any]] = {}
_ranges_cache: dict[int, tuple[float, list[str]]] = {}
_ranges_429_until: dict[int, float] = {}
RANGES_CACHE_TTL = 300.0


def _extract_csrf(text: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    meta = soup.find("meta", {"name": "csrf-token"})
    if meta and meta.get("content"):
        return str(meta["content"])
    token_input = soup.find("input", {"name": "_token"})
    if token_input and token_input.get("value"):
        return str(token_input["value"])
    match = re.search(
        r"""['_"]_token['"]\s*[,:]?\s*['"]([A-Za-z0-9_\-+/=]{20,})['"]""",
        text,
    )
    return match.group(1) if match else ""


def auto_login_ivas(acc: dict[str, Any]) -> bool:
    """
    Optional programmatic login. Credentials are read only from env.
    It is attempted once per failed request and never logged.
    """
    username = os.getenv("IVAS_USERNAME", "").strip()
    password = os.getenv("IVAS_PASSWORD", "")
    if not username or not password:
        return False

    lock: threading.Lock = acc["auth_lock"]
    if not lock.acquire(blocking=False):
        return False

    try:
        client: httpx.Client = acc["session"]
        login_page = client.get(f"{IVAS_BASE_URL}/login", timeout=10.0)
        if is_cloudflare_or_blocked(login_page):
            _log(
                "AUTH",
                f"akun #{acc['idx']} login ditahan Cloudflare "
                f"(HTTP {login_page.status_code})",
                Fore.YELLOW,
            )
            return False

        token = _extract_csrf(login_page.text)
        if not token:
            return False

        response = client.post(
            f"{IVAS_BASE_URL}/login",
            data={"_token": token, "email": username, "username": username, "password": password},
            headers={"Referer": f"{IVAS_BASE_URL}/login"},
            timeout=12.0,
        )
        if response.status_code in (401, 403) or is_login_redirect(response):
            return False
        if is_cloudflare_or_blocked(response):
            _log(
                "AUTH",
                f"akun #{acc['idx']} login ditahan Cloudflare "
                f"(HTTP {response.status_code})",
                Fore.YELLOW,
            )
            return False

        acc["csrf_token"] = _extract_csrf(response.text) or token
        _recv_csrf_cache.pop(acc["idx"], None)
        clear_system_alert(f"session:{acc['idx']}")
        _log("AUTH", f"akun #{acc['idx']} auto-login berhasil", Fore.GREEN)
        return True
    except Exception as exc:
        _log("AUTH", f"akun #{acc['idx']} auto-login error: {exc}", Fore.YELLOW)
        return False
    finally:
        lock.release()


def ivas_request(
    acc: dict[str, Any],
    method: str,
    path: str,
    *,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    auth_retry: bool = True,
) -> httpx.Response:
    """
    Shared IVAS request path:
    - reuses the per-account httpx connection pool
    - enforces only a tiny 50 ms local gate
    - retries 429 with bounded backoff
    - auto-login once after login redirect
    """
    client: httpx.Client = acc["session"]
    request_lock: threading.Lock = acc["request_lock"]

    for attempt in range(3):
        with request_lock:
            elapsed = time.monotonic() - acc["last_request"]
            if elapsed < MIN_REQUEST_GAP:
                _sleep(MIN_REQUEST_GAP - elapsed)
            acc["last_request"] = time.monotonic()

        response = client.request(
            method,
            f"{IVAS_BASE_URL}{path}",
            data=data,
            headers=headers,
        )

        if is_rate_limited(response):
            delay = (0.5, 1.5, 3.0)[attempt]
            _log("WORKER", f"rate limit IVAS, retry {attempt + 1}/3", Fore.YELLOW)
            _sleep(delay)
            continue

        if is_cloudflare_or_blocked(response):
            raise PortalBlocked(
                f"akun #{acc['idx']} portal ditahan Cloudflare "
                f"(HTTP {response.status_code}, URL {response.url})"
            )

        if response.status_code in (401, 403) or is_login_redirect(response):
            _log(
                "AUTH",
                f"akun #{acc['idx']} ditolak: HTTP {response.status_code}, "
                f"URL {response.url}",
                Fore.YELLOW,
            )
            if auth_retry and auto_login_ivas(acc):
                return ivas_request(
                    acc,
                    method,
                    path,
                    data=data,
                    headers=headers,
                    auth_retry=False,
                )
            raise SessionExpired(f"akun #{acc['idx']} session expired")

        return response

    raise RateLimited(f"akun #{acc['idx']} rate limited")


def get_recv_csrf(acc: dict[str, Any]) -> str:
    idx = acc["idx"]
    cached = _recv_csrf_cache.get(idx)
    if cached and time.time() - cached["ts"] < 900.0:
        return str(cached["csrf"])

    response = ivas_request(acc, "GET", "/portal/sms/received")
    token = _extract_csrf(response.text)
    if token:
        acc["csrf_token"] = token
        _recv_csrf_cache[idx] = {"csrf": token, "ts": time.time()}
        return token
    return str(acc.get("csrf_token", ""))


def get_ranges(acc: dict[str, Any]) -> list[str]:
    idx = acc["idx"]
    now = time.time()

    if now < _ranges_429_until.get(idx, 0.0):
        cached = _ranges_cache.get(idx)
        return cached[1] if cached else []

    cached = _ranges_cache.get(idx)
    if cached and now - cached[0] < RANGES_CACHE_TTL:
        return cached[1]

    today = datetime.now().strftime("%Y-%m-%d")
    csrf = get_recv_csrf(acc)
    response = ivas_request(
        acc,
        "POST",
        "/portal/sms/received/getsms",
        data={"_token": csrf, "from": today, "to": today},
        headers=_recv_headers(IVAS_BASE_URL),
    )

    if response.status_code == 429:
        _ranges_429_until[idx] = now + 60.0
        return cached[1] if cached else []

    soup = BeautifulSoup(response.text, "html.parser")
    ranges: list[str] = []
    for div in soup.find_all("div", onclick=True):
        onclick = str(div.get("onclick", ""))
        if "toggleRange" in onclick:
            parts = onclick.split("'")
            if len(parts) > 1:
                ranges.append(parts[1])

    result = list(dict.fromkeys(ranges))
    if result:
        _ranges_cache[idx] = (now, result)
    _ranges_429_until.pop(idx, None)
    return result


def get_ranges_cached(acc: dict[str, Any]) -> list[str]:
    return get_ranges(acc)


def get_numbers(acc: dict[str, Any], rng: str) -> list[str]:
    today = datetime.now().strftime("%Y-%m-%d")
    response = ivas_request(
        acc,
        "POST",
        "/portal/sms/received/getsms/number",
        data={
            "_token": get_recv_csrf(acc),
            "start": today,
            "end": today,
            "range": rng,
        },
        headers=_recv_headers(IVAS_BASE_URL),
    )

    soup = BeautifulSoup(response.text, "html.parser")
    values: list[str] = []
    for div in soup.find_all("div", onclick=True):
        parts = str(div.get("onclick", "")).split("'")
        if len(parts) > 1 and parts[1] and parts[1] != rng:
            values.append(parts[1])
    return list(dict.fromkeys(values))


def get_sms(acc: dict[str, Any], rng: str, number: str) -> list[str]:
    today = datetime.now().strftime("%Y-%m-%d")
    response = ivas_request(
        acc,
        "POST",
        "/portal/sms/received/getsms/number/sms",
        data={
            "_token": get_recv_csrf(acc),
            "start": today,
            "end": today,
            "Number": number,
            "Range": rng,
        },
        headers=_recv_headers(IVAS_BASE_URL),
    )

    values: list[str] = []
    soup = BeautifulSoup(response.text, "html.parser")
    for raw in soup.stripped_strings:
        value = raw.strip().replace("<#>", "").strip()
        if not value or "No SMS Found" in value:
            continue
        if re.fullmatch(r"[A-Za-z0-9]{10,}", value):
            continue
        if re.search(r"\b\d{2}:\d{2}:\d{2}\b", value):
            continue
        if "$" in value:
            continue
        if value.lower() in {"sender", "revenue", "time"}:
            continue
        values.append(value)
    return list(dict.fromkeys(values))


# ============================================================================
# POLLING
# ============================================================================


def poll_one(acc: dict[str, Any]) -> bool:
    found = False
    try:
        ranges = get_ranges_cached(acc)
    except (SessionExpired, RateLimited, PortalBlocked) as exc:
        _log("RANGE", str(exc), Fore.YELLOW)
        key = f"portal:{acc['idx']}"
        clear_system_alert(f"session:{acc['idx']}")
        system_alert_once(
            key,
            f"⚠️ <b>IVAS portal tidak bisa diakses</b>\n"
            f"Akun #{acc['idx']}: <code>{esc(exc)}</code>",
        )
        return False
    except Exception as exc:
        _log("RANGE", f"akun #{acc['idx']}: {exc}", Fore.YELLOW)
        return False

    def process_number(
        task: tuple[str, str, str, str],
    ) -> bool:
        rng, number, fallback_country, country_code = task
        full_number = normalize_number(number, country_code)
        if not full_number.isdigit():
            return False

        try:
            sms_list = get_sms(acc, rng, number)
        except (SessionExpired, PortalBlocked):
            system_alert_once(
                f"portal:{acc['idx']}",
                f"⚠️ <b>IVAS portal tidak bisa diakses</b>\n"
                f"Akun #{acc['idx']} cek cookie, domain, dan Cloudflare.",
            )
            return False
        except Exception as exc:
            _log("SMS", f"akun #{acc['idx']}: {exc}", Fore.YELLOW)
            return False

        local_found = False
        for sms in sms_list:
            clean = normalize_sms_for_display(sms)
            uid = hashlib.sha256(f"{number}-{clean}".encode()).hexdigest()
            with _sent_cache_lock:
                if uid in sent_cache:
                    continue

            otp = extract_otp(clean)
            if not otp:
                continue

            region, flag = detect_country(full_number, country_code or fallback_country)
            country_name = country_name_and_language(full_number, region, clean)
            message = build_otp_message(
                otp,
                flag,
                region,
                full_number,
                clean,
                country_name,
            )
            tg_send_otp(otp, message)
            cache_add(uid)
            _log(
                "OTP",
                f"{detect_service(clean):<10} {flag} #{region} "
                f"{mask_phone(full_number)} → {otp}",
                Fore.GREEN,
            )
            local_found = True
        return local_found

    tasks: list[tuple[str, str, str, str]] = []
    for rng in ranges:
        fallback_country, country_code = parse_range(rng)
        try:
            numbers = get_numbers(acc, rng)
        except (SessionExpired, PortalBlocked):
            system_alert_once(
                f"portal:{acc['idx']}",
                f"⚠️ <b>IVAS portal tidak bisa diakses</b>\n"
                f"Akun #{acc['idx']} cek cookie, domain, dan Cloudflare.",
            )
            continue
        except Exception as exc:
            _log("NUM", f"akun #{acc['idx']}: {exc}", Fore.YELLOW)
            continue
        tasks.extend((rng, number, fallback_country, country_code) for number in numbers)

    # Paralel terbatas: maksimal 3 request SMS dalam satu akun.
    if not tasks:
        return False
    with ThreadPoolExecutor(
        max_workers=min(MAX_NUMBER_WORKERS, len(tasks)),
        thread_name_prefix=f"sms-{acc['idx']}",
    ) as pool:
        futures = [pool.submit(process_number, task) for task in tasks]
        for future in as_completed(futures):
            try:
                found = future.result() or found
            except Exception as exc:
                _log("NUM", f"akun #{acc['idx']}: {exc}", Fore.YELLOW)
    return found


def account_worker(acc: dict[str, Any]) -> None:
    while True:
        try:
            found = poll_one(acc)
            # Polling tetap cepat setelah OTP, tetapi tidak busy-loop.
            delay = POLL_INTERVAL_MIN if found else (
                POLL_INTERVAL_MIN
                + (POLL_INTERVAL_MAX - POLL_INTERVAL_MIN) * 0.5
            )
        except Exception as exc:
            _log("WORKER", f"akun #{acc['idx']}: {exc}", Fore.RED)
            delay = POLL_INTERVAL_MAX

        _sleep(delay)


def keepalive_worker(accounts: list[dict[str, Any]]) -> None:
    _log("KEEPALIVE", f"aktif — tiap {KEEPALIVE_INTERVAL:.0f}s", Fore.CYAN)
    while True:
        for acc in accounts:
            idx = acc["idx"]
            try:
                response = ivas_request(
                    acc,
                    "GET",
                    "/portal",
                    auth_retry=True,
                )
                if response.status_code < 400 and not is_login_redirect(response):
                    _recv_csrf_cache.pop(idx, None)
                    clear_system_alert(f"session:{idx}")
                    clear_system_alert(f"portal:{idx}")
                    _log("KA-OK", f"akun #{idx} session aktif", Fore.GREEN)
            except PortalBlocked as exc:
                _log("KA-WARN", str(exc), Fore.YELLOW)
                system_alert_once(
                    f"portal:{idx}",
                    f"⚠️ <b>IVAS ACCESS BLOCKED</b>\n"
                    f"Akun #{idx} terkena challenge/403 dari portal. "
                    f"Cookie browser bisa terikat ke IP atau sesi browser.",
                )
            except SessionExpired as exc:
                _log("KA-WARN", str(exc), Fore.YELLOW)
                _log("KA-WARN", f"akun #{idx} session expired", Fore.YELLOW)
                system_alert_once(
                    f"session:{idx}",
                    f"⚠️ <b>IVAS SESSION / ACCESS ERROR</b>\n"
                    f"Akun #{idx} gagal akses portal. Cek cookie, domain, "
                    f"Cloudflare, atau IVAS_USERNAME/IVAS_PASSWORD.",
                )
            except Exception as exc:
                _log("KA-ERR", f"akun #{idx}: {exc}", Fore.YELLOW)
            _sleep(0.05)
        _sleep(KEEPALIVE_INTERVAL)


# ============================================================================
# COMMAND LISTENER
# ============================================================================


def handle_command(update: dict[str, Any]) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    chat_type = chat.get("type", "")
    chat_name = chat.get("title") or chat.get("username") or str(chat_id)
    text = str(message.get("text") or "").strip()
    command = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""

    if command == "/addbot":
        if chat_type not in {"group", "supergroup"}:
            tg_send_msg(chat_id, "⚠️ <b>/addbot hanya bisa dipakai di grup.</b>")
            return
        if add_group(int(chat_id)):
            tg_send_msg(
                chat_id,
                f"✅ <b>BOT AKTIF</b>\n"
                f"Grup: <b>{esc(chat_name)}</b>\n"
                f"OTP akan diteruskan otomatis.",
            )
        else:
            tg_send_msg(chat_id, "ℹ️ Grup ini sudah terdaftar.")

    elif command == "/removebot":
        if chat_type not in {"group", "supergroup"}:
            return
        if int(chat_id) == DEFAULT_TARGET:
            tg_send_msg(chat_id, "⛔ Grup utama tidak bisa dihapus.")
        elif remove_group(int(chat_id)):
            tg_send_msg(chat_id, "🗑️ Grup dihapus dari target OTP.")
        else:
            tg_send_msg(chat_id, "ℹ️ Grup tidak terdaftar.")

    elif command == "/listbot":
        groups = list_groups()
        body = "\n".join(f"• <code>{gid}</code>" for gid in groups)
        tg_send_msg(chat_id, f"<b>👥 GRUP AKTIF</b>\n\n{body}\n\nTotal: {len(groups)}")


def tg_update_listener() -> None:
    offset = 0
    conflict_count = 0
    _log("CMD", "update listener aktif", Fore.CYAN)
    while True:
        try:
            data = _tg_post(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 30,
                    "allowed_updates": ["message", "edited_message"],
                },
                retries=2,
            )
            if not data.get("ok"):
                description = str(data.get("description", ""))
                if "Conflict" in description:
                    conflict_count += 1
                    wait = min(60.0, 5.0 * conflict_count)
                    _log(
                        "CMD",
                        "Telegram Conflict: ada instance lain memakai token "
                        f"(percobaan {conflict_count}, retry {wait:.0f}s)",
                        Fore.RED,
                    )
                    _sleep(wait)
                else:
                    conflict_count = 0
                    _sleep(1.0)
                continue
            conflict_count = 0
            for update in data.get("result", []):
                offset = int(update["update_id"]) + 1
                try:
                    handle_command(update)
                except Exception as exc:
                    _log("CMD", f"handle error: {exc}", Fore.YELLOW)
        except httpx.TimeoutException:
            continue
        except Exception as exc:
            _log("CMD", f"listener error: {exc}", Fore.YELLOW)
            _sleep(1.0)


# ============================================================================
# HEALTH SERVER + SHUTDOWN
# ============================================================================


_bot_start_time = time.time()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        route = self.path.split("?", 1)[0].rstrip("/") or "/"
        if route in {"/", "/health"}:
            self._respond(200, "text/plain; charset=utf-8", b"OK")
            return
        if route == "/status":
            uptime = int(time.time() - _bot_start_time)
            body = json.dumps(
                {
                    "status": "running",
                    "uptime_seconds": uptime,
                    "targets": list_groups(),
                    "poll_interval_seconds": [POLL_INTERVAL_MIN, POLL_INTERVAL_MAX],
                    "number_workers": MAX_NUMBER_WORKERS,
                }
            ).encode()
            self._respond(200, "application/json; charset=utf-8", body)
            return
        self._respond(404, "text/plain; charset=utf-8", b"Not found")

    def _respond(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        return


def run_health_server() -> None:
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    _log("SERVER", f"port {port} | /health | /status", Fore.CYAN)
    server.serve_forever()


def shutdown(_signum: int, _frame: Any) -> None:
    _log("SHUTDOWN", "menyimpan cache lalu keluar...", Fore.YELLOW)
    save_sent_cache_now()
    _save_groups()
    try:
        _tg_client.close()
    except Exception:
        pass
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)


# ============================================================================
# MAIN
# ============================================================================


def main() -> None:
    print(Fore.CYAN + Style.BRIGHT)
    print("  ╔══════════════════════════════════════╗")
    print("  ║   🕷  SPIDERMAT OTP BOT              ║")
    print("  ║        OPTIMIZED FOR RAILWAY         ║")
    print("  ╚══════════════════════════════════════╝")
    print(Style.RESET_ALL)

    if not BOT_TOKEN:
        _log("FATAL", "BOT_TOKEN belum diset di Railway Variables", Fore.RED)
        raise SystemExit(1)

    _load_groups()
    cookies_list = load_cookies()
    if not cookies_list:
        _log("FATAL", f"Tidak ada cookie valid di {COOKIE_FILE}", Fore.RED)
        raise SystemExit(1)

    accounts: list[dict[str, Any]] = []
    for idx, cookies in enumerate(cookies_list):
        account = {
            "idx": idx,
            "cookies": cookies,
            "session": make_http_client(cookies),
            "csrf_token": "",
            "request_lock": threading.Lock(),
            "auth_lock": threading.Lock(),
            "last_request": 0.0,
        }
        accounts.append(account)
        _log("COOKIE", f"akun #{idx}: {len(cookies)} cookie dimuat", Fore.GREEN)

    _log("CONFIG", f"target: {list_groups()}", Fore.CYAN)
    _log("CONFIG", f"poll interval: {POLL_INTERVAL_MIN:.1f}–{POLL_INTERVAL_MAX:.1f}s", Fore.CYAN)
    _log("CONFIG", f"SMS workers/account: {MAX_NUMBER_WORKERS}", Fore.CYAN)
    _log("CONFIG", f"channel: {CHANNEL_LINK}", Fore.CYAN)

    threading.Thread(target=run_health_server, daemon=True, name="health").start()
    threading.Thread(target=tg_update_listener, daemon=True, name="telegram-updates").start()
    threading.Thread(
        target=keepalive_worker,
        args=(accounts,),
        daemon=True,
        name="keepalive",
    ).start()

    for account in accounts:
        threading.Thread(
            target=account_worker,
            args=(account,),
            daemon=True,
            name=f"poll-{account['idx']}",
        ).start()
        _log("THREAD+", f"akun #{account['idx']} polling aktif", Fore.GREEN)

    _log("CONFIG", "Bot berjalan. Ketik /addbot di grup target.", Fore.CYAN)

    global _cache_dirty, _last_cache_save
    while True:
        if _cache_dirty and time.time() - _last_cache_save >= 5.0:
            save_sent_cache_now()
            _last_cache_save = time.time()
            _cache_dirty = False
        _sleep(1.0)


if __name__ == "__main__":
    main()