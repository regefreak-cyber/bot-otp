"""
SPIDERMAT OTP BOT — FORWARD MODE
Baca cookie dari cookie.json → poll IVAS → forward OTP ke Telegram.
Command: /addbot /removebot /listbot
"""

import httpx
from bs4 import BeautifulSoup
import re
from datetime import datetime
import time
import threading
import json
import os
import hashlib
import signal
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests
import phonenumbers
from phonenumbers import geocoder
from colorama import init, Fore, Style

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
init(autoreset=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOT_TOKEN    = os.getenv("BOT_TOKEN", "")   # wajib diset via env var
OWNER_ID     = int(os.getenv("OWNER_ID", "0"))

# Grup default yang SELALU menerima OTP (tetap ada meskipun tidak /addbot)
DEFAULT_TARGET = -1003686221386

CHANNEL_LINK = "https://t.me/matttttcha"
NUMBER_LINK  = "https://t.me/matttttcha"

COOKIE_FILE        = "cookie.json"
CACHE_FILE         = "file/sent_cache.json"
GROUPS_FILE        = "file/groups.json"     # daftar grup tambahan via /addbot
MAX_CACHE          = 2000
POLL_INTERVAL_MAX  = 12.0
KEEPALIVE_INTERVAL = 480    # detik — ping /portal tiap 8 menit

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LOGGING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_LOG_ICONS = {
    "OTP":      "🟢",
    "COOKIE":   "🍪",
    "CONFIG":   "⚙️ ",
    "WORKER":   "🔄",
    "RANGE":    "📡",
    "CSRF":     "🔑",
    "KA-OK":    "💚",
    "KA-WARN":  "🟡",
    "KA-ERR":   "🔴",
    "KEEPALIVE":"🫀",
    "SERVER":   "🌐",
    "CACHE":    "💾",
    "TG-ERR":   "❌",
    "NUM":      "📟",
    "SMS":      "📨",
    "THREAD+":  "🧵",
    "SHUTDOWN": "🛑",
    "FATAL":    "💀",
    "CMD":      "⌨️ ",
    "GROUP":    "👥",
}

def _log(tag, msg, color=Fore.CYAN):
    icon  = _LOG_ICONS.get(tag, "•")
    ts    = datetime.now().strftime("%H:%M:%S")
    label = f"{icon} {tag:<9}"
    print(color + f"  {ts}  {label}  {msg}" + Style.RESET_ALL, flush=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WORKER POOL  (proxy fallback jika kena rate-limit)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WORKER_POOL = [
    "https://plain-butterfly-d9e9.kicenivas.workers.dev",
    "https://ivasmunchen.serverprivate1.web.id",
    "https://ivasmsbykicenv2.kikixrakaofficial.biz.id",
    "https://ivasbykiven.alwayskixyzshop.web.id",
]

_worker_lock          = threading.Lock()
_active_worker_idx    = 0
_worker_limited_until = {}
_last_log_limit_time  = 0
WORKER_LIMIT_COOLDOWN = 900   # 15 menit

def get_base():
    with _worker_lock:
        return WORKER_POOL[_active_worker_idx % len(WORKER_POOL)]

def mark_worker_limited(url):
    global _active_worker_idx, _last_log_limit_time
    now = time.time()
    should_log = False
    with _worker_lock:
        _worker_limited_until[url] = now + WORKER_LIMIT_COOLDOWN
        for i in range(1, len(WORKER_POOL) + 1):
            idx = (_active_worker_idx + i) % len(WORKER_POOL)
            if _worker_limited_until.get(WORKER_POOL[idx], 0) < now:
                _active_worker_idx = idx
                break
        if now - _last_log_limit_time > 3.0:
            _last_log_limit_time = now
            should_log = True

    if should_log:
        _log("WORKER", f"rate-limited → pindah ke {get_base()}", Fore.YELLOW)
    time.sleep(1.0)

_RATE_LIMIT_MARKERS = (
    "temporarily rate limited", "error 1027", "please check back later",
    "has been rate limited", "error 1015", "you have been blocked",
    "attention required", "error 1020", "checking your browser", "just a moment",
)

def is_worker_blocked(resp) -> bool:
    if resp is None:
        return False
    try:
        if resp.status_code in (429, 503):
            return True
        sample = resp.text[:2000].lower()
        return any(m in sample for m in _RATE_LIMIT_MARKERS)
    except:
        return False

def load_cookies():
    if not os.path.exists(COOKIE_FILE):
        _log("COOKIE", f"{COOKIE_FILE} tidak ditemukan!", Fore.RED)
        return []
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            return []
        if isinstance(data, list):
            if all(isinstance(x, dict) and "name" in x and "value" in x for x in data):
                return [{x["name"]: x["value"] for x in data}]
            return data
        if isinstance(data, dict) and all(isinstance(v, dict) for v in data.values()):
            return list(data.values())
        if isinstance(data, dict):
            return [data]
    except Exception as e:
        _log("COOKIE", f"error load {COOKIE_FILE}: {e}", Fore.RED)
    return []

def make_session(cookies: dict, timeout=30):
    hdrs = {
        "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Origin":           "https://ivasms.com",
        "Referer":          "https://ivasms.com/",
    }
    s = httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers=hdrs,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    s.cookies.update(cookies)
    return s

_recv_csrf_cache = {}
RECV_CSRF_TTL    = 900

def get_recv_csrf(acc, _retry=0) -> str:
    idx    = acc["idx"]
    now    = time.time()
    cached = _recv_csrf_cache.get(idx)
    if cached and (now - cached["ts"]) < RECV_CSRF_TTL:
        return cached["csrf"]
    base     = get_base()
    recv_url = f"{base}/portal/sms/received"
    try:
        worker_before = base
        r = acc["session"].get(recv_url, timeout=15)
        if is_worker_blocked(r) and _retry < len(WORKER_POOL) - 1:
            mark_worker_limited(worker_before)
            return get_recv_csrf(acc, _retry + 1)
        if "/login" in str(r.url):
            return acc.get("csrf_token", "")
        soup = BeautifulSoup(r.text, "html.parser")
        csrf = ""
        meta = soup.find("meta", {"name": "csrf-token"})
        if meta:
            csrf = meta.get("content", "")
        if not csrf:
            inp = soup.find("input", {"name": "_token"})
            if inp:
                csrf = inp.get("value", "")
        if not csrf:
            m = re.search(r"['\"]_token['\"]\s*[,:]?\s*['\"]([A-Za-z0-9_\-+/=]{20,})['\"]", r.text)
            if m:
                csrf = m.group(1)
        if csrf:
            acc["csrf_token"] = csrf
            _recv_csrf_cache[idx] = {"csrf": csrf, "ts": now}
            return csrf
    except Exception as e:
        _log("CSRF", f"akun #{idx}: {e}", Fore.YELLOW)
    return acc.get("csrf_token", "")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# IVAS API  (ranges / numbers / sms)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_ranges_cache     = {}   # idx -> (ts, list)
_ranges_429_until = {}   # idx -> ts
RANGES_CACHE_TTL  = 300  # 5 menit

def _recv_headers(base):
    return {
        "Accept":           "text/html,*/*;q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type":     "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer":          f"{base}/portal/sms/received",
        "Origin":           "https://ivasms.com",
    }

def get_ranges(acc, _retry=0):
    idx = acc["idx"]
    now = time.time()
    if now < _ranges_429_until.get(idx, 0):
        entry = _ranges_cache.get(idx)
        return entry[1] if entry else []
    base          = get_base()
    today         = datetime.now().strftime("%Y-%m-%d")
    csrf          = get_recv_csrf(acc)
    worker_before = base
    r = acc["session"].post(
        f"{base}/portal/sms/received/getsms",
        data={"_token": csrf, "from": today, "to": today},
        headers=_recv_headers(base),
    )
    if is_worker_blocked(r) and _retry < len(WORKER_POOL) - 1:
        mark_worker_limited(worker_before)
        return get_ranges(acc, _retry + 1)
    if r.status_code == 429:
        _ranges_429_until[idx] = now + 180
        entry = _ranges_cache.get(idx)
        _log("RANGE", f"akun #{idx} — 429, cooldown 3 menit, pakai cache lama", Fore.YELLOW)
        return entry[1] if entry else []
    if "/login" in str(r.url):
        return []
    soup   = BeautifulSoup(r.text, "html.parser")
    ranges = []
    for div in soup.find_all("div", onclick=True):
        if "toggleRange" in div["onclick"]:
            try:
                ranges.append(div["onclick"].split("'")[1])
            except:
                pass
    result = list(set(ranges))
    _ranges_429_until.pop(idx, None)
    if result:
        _ranges_cache[idx] = (now, result)
    return result

def get_ranges_cached(acc):
    idx  = acc["idx"]
    now  = time.time()
    if now < _ranges_429_until.get(idx, 0):
        entry = _ranges_cache.get(idx)
        return entry[1] if entry else []
    entry = _ranges_cache.get(idx)
    if entry:
        ts, cached = entry
        if now - ts < RANGES_CACHE_TTL:
            return cached
    return get_ranges(acc)

def get_numbers(acc, rng, _retry=0):
    time.sleep(0.4)
    base          = get_base()
    today         = datetime.now().strftime("%Y-%m-%d")
    csrf          = get_recv_csrf(acc)
    worker_before = base
    r = acc["session"].post(
        f"{base}/portal/sms/received/getsms/number",
        data={"_token": csrf, "start": today, "end": today, "range": rng},
        headers=_recv_headers(base),
    )
    if is_worker_blocked(r) and _retry < len(WORKER_POOL) - 1:
        mark_worker_limited(worker_before)
        return get_numbers(acc, rng, _retry + 1)
    if r.status_code == 429 or "/login" in str(r.url):
        return []
    soup    = BeautifulSoup(r.text, "html.parser")
    numbers = []
    for div in soup.find_all("div", onclick=True):
        try:
            val = div["onclick"].split("'")[1]
            if val and val != rng:
                numbers.append(val)
        except:
            pass
    return list(set(numbers))
    
def get_sms(acc, rng, number, _retry=0):
    time.sleep(0.3)
    base          = get_base()
    today         = datetime.now().strftime("%Y-%m-%d")
    csrf          = get_recv_csrf(acc)
    worker_before = base
    r = acc["session"].post(
        f"{base}/portal/sms/received/getsms/number/sms",
        data={"_token": csrf, "start": today, "end": today, "Number": number, "Range": rng},
        headers=_recv_headers(base),
    )
    if is_worker_blocked(r) and _retry < len(WORKER_POOL) - 1:
        mark_worker_limited(worker_before)
        return get_sms(acc, rng, number, _retry + 1)
    if r.status_code == 429 or "/login" in str(r.url):
        return []
    soup      = BeautifulSoup(r.text, "html.parser")
    sms_texts = []
    try:
        for t in soup.stripped_strings:
            t = t.strip().replace("<#>", "").strip()
            if re.fullmatch(r"[A-Za-z0-9]{10,}", t):
                continue
            t_low = t.lower()
            if any(x in t_low for x in ["sender", "revenue", "time"]):
                continue
            if re.search(r"\b\d{2}:\d{2}:\d{2}\b", t):
                continue
            if "$" in t:
                continue
            if t and "No SMS Found" not in t:
                sms_texts.append(t)
    except Exception as e:
        _log("SMS", f"parse error: {e}", Fore.RED)
    return list(dict.fromkeys(sms_texts))
    

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PLATFORM DETECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SERVICE_INFO = {
    "WHATSAPP":  {"icon": "💬",  "name": "WhatsApp",  "short": "#WS"},
    "TELEGRAM":  {"icon": "✈️",  "name": "Telegram",  "short": "#TG"},
    "GOOGLE":    {"icon": "🔍",  "name": "Google",    "short": "#G" },
    "FACEBOOK":  {"icon": "📘",  "name": "Facebook",  "short": "#FB"},
    "INSTAGRAM": {"icon": "📷",  "name": "Instagram", "short": "#IG"},
    "TIKTOK":    {"icon": "🎵",  "name": "TikTok",    "short": "#TT"},
    "GRAB":      {"icon": "🚗",  "name": "Grab",      "short": "#GR"},
    "GOJEK":     {"icon": "🛵",  "name": "Gojek",     "short": "#GJ"},
    "SHOPEE":    {"icon": "🟠",  "name": "Shopee",    "short": "#SP"},
    "TOKOPEDIA": {"icon": "🛍️", "name": "Tokopedia", "short": "#TP"},
}
_SVC_DEFAULT = {"icon": "💌", "name": "OTP", "short": "#OT"}

_SVC_PATTERN = re.compile(
    r"(WhatsApp|Telegram|Google|Facebook|Instagram|TikTok|Grab|Gojek|Shopee|Tokopedia)",
    re.IGNORECASE,
)

def detect_service(text: str) -> dict:
    m = _SVC_PATTERN.search(text)
    if m:
        return SERVICE_INFO.get(m.group(1).upper(), _SVC_DEFAULT)
    return _SVC_DEFAULT

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHONE / COUNTRY HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def code_to_flag(code: str) -> str:
    try:
        return "".join(chr(127397 + ord(c)) for c in code.upper())
    except:
        return "🏳"

def detect_country_and_flag(full_num: str, fallback_country="UNKNOWN"):
    try:
        parsed  = phonenumbers.parse("+" + full_num, None)
        region  = phonenumbers.region_code_for_number(parsed)
        if region:
            flag         = code_to_flag(region)
            country_name = geocoder.description_for_number(parsed, "en")
            return (country_name.upper() if country_name else fallback_country), flag, region
    except:
        pass
    return fallback_country, "🏳", "??"

def parse_range(rng: str):
    country    = re.sub(r"\s*\(.*?\)", "", rng)
    country    = re.sub(r"\d+", "", country)
    country    = re.sub(r"\s+", " ", country).strip().upper()
    code_match = re.search(r"\((\d+)\)", rng)
    code       = code_match.group(1) if code_match else ""
    return country, code

def normalize_number(num: str, country_code: str) -> str:
    num = str(num).strip().replace(" ", "").replace("-", "").replace("+", "")
    if country_code and num.startswith(country_code):
        return num
    if num.startswith("0") and country_code:
        return country_code + num[1:]
    return num

def mask_phone(number: str) -> str:
    return str(number)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MESSAGE BUILDER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def build_otp_message(
    otp: str,
    svc: dict,
    flag: str,
    country: str,
    region_code: str,
    masked_num: str,
) -> str:
    raw_num = re.sub(r"\D", "", str(masked_num))

    # Masking nomor telepon & tebelin
    if len(raw_num) >= 8:
        phone_formatted = f"<b>{raw_num[:4]}•SPDRMT•{raw_num[-4:]}</b>"
    else:
        phone_formatted = f"<b>{raw_num}</b>"

    prefix = raw_num[:6] if len(raw_num) >= 6 else raw_num

    return (
        f"¤ {flag} <b>{region_code}</b> ¤ {phone_formatted} ¤\n"
        f"\n"
        f"<b>Prefix:</b> <tg-spoiler>{prefix}</tg-spoiler>"
    )
    
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SENT CACHE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_sent_cache_lock = threading.Lock()
_cache_dirty     = False
_last_cache_save = 0.0

def load_sent_cache() -> set:
    os.makedirs("file", exist_ok=True)
    if not os.path.exists(CACHE_FILE):
        return set()
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data) if isinstance(data, list) else set()
    except:
        return set()

def save_sent_cache_now(cache: set):
    try:
        os.makedirs("file", exist_ok=True)
        lst = list(cache)
        if len(lst) > MAX_CACHE:
            lst = lst[-MAX_CACHE:]
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(lst, f)
    except Exception as e:
        _log("CACHE", f"save error: {e}", Fore.YELLOW)

sent_cache = load_sent_cache()

def cache_add(uid: str):
    global _cache_dirty, _last_cache_save
    with _sent_cache_lock:
        sent_cache.add(uid)
    _cache_dirty = True
    if time.time() - _last_cache_save >= 5:
        with _sent_cache_lock:
            save_sent_cache_now(sent_cache)
        _last_cache_save = time.time()
        _cache_dirty = False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GROUP TARGETS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_targets_lock    = threading.Lock()
_forward_targets: set = {DEFAULT_TARGET}

def _load_groups():
    if not os.path.exists(GROUPS_FILE):
        return
    try:
        with open(GROUPS_FILE, "r", encoding="utf-8") as f:
            ids = json.load(f)
        if isinstance(ids, list):
            with _targets_lock:
                for gid in ids:
                    _forward_targets.add(int(gid))
        _log("GROUP", f"{len(ids)} grup dimuat dari {GROUPS_FILE}", Fore.CYAN)
    except Exception as e:
        _log("GROUP", f"load error: {e}", Fore.YELLOW)

def _save_groups():
    try:
        os.makedirs("file", exist_ok=True)
        with _targets_lock:
            ids = list(_forward_targets)
        with open(GROUPS_FILE, "w", encoding="utf-8") as f:
            json.dump(ids, f)
    except Exception as e:
        _log("GROUP", f"save error: {e}", Fore.YELLOW)

def add_group(chat_id: int) -> bool:
    with _targets_lock:
        if chat_id in _forward_targets:
            return False
        _forward_targets.add(chat_id)
    _save_groups()
    return True

def remove_group(chat_id: int) -> bool:
    with _targets_lock:
        if chat_id not in _forward_targets or chat_id == DEFAULT_TARGET:
            return False
        _forward_targets.discard(chat_id)
    _save_groups()
    return True

def list_groups() -> list:
    with _targets_lock:
        return list(_forward_targets)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TELEGRAM SEND
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_tg_session = requests.Session()
_tg_session.mount("https://", requests.adapters.HTTPAdapter(
    pool_connections=4, pool_maxsize=10, max_retries=0,
))

def _tg_post(chat_id, text, reply_markup=None, retries=3):
    payload = {
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    for attempt in range(retries):
        try:
            r    = _tg_session.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json=payload,
                timeout=10,
            )
            data = r.json()
            if data.get("ok"):
                return True
            if r.status_code == 429:
                wait = data.get("parameters", {}).get("retry_after", 5)
                time.sleep(wait + 1)
                continue
            _log("TG-ERR", f"chat {chat_id}: {data.get('description', '?')}", Fore.RED)
            return False
        except Exception as e:
            if attempt == retries - 1:
                _log("TG-ERR", f"chat {chat_id}: {e}", Fore.RED)
            else:
                time.sleep(1.5 ** (attempt + 1))
    return False

def tg_send_msg(chat_id: int, text: str):
    _tg_post(chat_id, text)

def tg_send_otp(otp: str, msg_text: str):
    kb = {
        "inline_keyboard": [
            [{"text": f"{otp}", "copy_text": {"text": otp}}],
            [{"text": "All Files", "url": "https://t.me/matchaappp"}],
        ]
    }
    targets = list_groups()

    def _send_one(cid):
        _tg_post(cid, msg_text, reply_markup=kb)

    if len(targets) == 1:
        _send_one(targets[0])
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(targets)), thread_name_prefix="tgsend") as pool:
            list(pool.map(_send_one, targets))
            
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COMMAND HANDLER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def handle_command(update: dict):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    chat      = msg.get("chat", {})
    chat_id   = chat.get("id")
    chat_type = chat.get("type", "")
    chat_name = chat.get("title") or chat.get("username") or str(chat_id)
    user      = msg.get("from", {})
    user_id   = user.get("id", 0)
    text      = (msg.get("text") or "").strip()

    cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""

    if cmd == "/addbot":
        if chat_type not in ("group", "supergroup"):
            tg_send_msg(chat_id,
                "⚠️ <b>Perintah ini hanya bisa digunakan di dalam grup.</b>\n"
                "Tambahkan bot ke grup, lalu ketik <code>/addbot</code> di grup tersebut.")
            return

        if add_group(chat_id):
            _log("GROUP", f"✅ ditambahkan: {chat_name} ({chat_id})", Fore.GREEN)
            tg_send_msg(chat_id,
                f"╔{'═' * 26}╗\n"
                f"  ✅  <b>BOT AKTIF</b>\n"
                f"╚{'═' * 26}╝\n"
                f"\n"
                f"🏠  <b>{chat_name}</b>\n"
                f"🆔  <code>{chat_id}</code>\n"
                f"\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✦  Grup ini sudah terdaftar.\n"
                f"✦  OTP akan diteruskan ke sini secara otomatis.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"\n"
                f"<i>Gunakan /removebot untuk menonaktifkan.</i>")
        else:
            tg_send_msg(chat_id,
                f"ℹ️  <b>{chat_name}</b> sudah terdaftar sebelumnya.\n"
                f"Bot sudah aktif di grup ini.")

    elif cmd == "/removebot":
        if chat_type not in ("group", "supergroup"):
            return

        if chat_id == DEFAULT_TARGET:
            tg_send_msg(chat_id,
                "⛔  Grup utama tidak bisa dihapus dari daftar target.")
            return

        if remove_group(chat_id):
            _log("GROUP", f"🗑️  dihapus: {chat_name} ({chat_id})", Fore.YELLOW)
            tg_send_msg(chat_id,
                f"🗑️  <b>{chat_name}</b> telah dikeluarkan dari daftar penerima OTP.\n"
                f"Ketik /addbot untuk mendaftarkan kembali.")
        else:
            tg_send_msg(chat_id,
                f"ℹ️  Grup ini tidak ada dalam daftar terdaftar.")

    elif cmd == "/listbot":
        groups  = list_groups()
        lines   = [f"  {i+1}.  <code>{gid}</code>" for i, gid in enumerate(groups)]
        total   = len(groups)
        tg_send_msg(chat_id,
            f"╔{'═' * 26}╗\n"
            f"  👥  <b>DAFTAR GRUP AKTIF</b>\n"
            f"╚{'═' * 26}╝\n"
            f"\n"
            + "\n".join(lines) +
            f"\n\n<i>Total: {total} grup terdaftar</i>")

def tg_update_listener():
    offset  = 0
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    _log("CMD", "update listener aktif", Fore.CYAN)

    while True:
        try:
            resp = _tg_session.post(
                api_url,
                json={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
                timeout=40,
            )
            data = resp.json()
            if not data.get("ok"):
                time.sleep(5)
                continue

            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    handle_command(upd)
                except Exception as e:
                    _log("CMD", f"handle error: {e}", Fore.YELLOW)

        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            _log("CMD", f"listener error: {e}", Fore.YELLOW)
            time.sleep(5)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POLL ONE ACCOUNT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_OTP_RE = re.compile(r"\b\d{3}[- ]?\d{3}\b")

def poll_one(acc) -> bool:
    found  = False
    ranges = []
    try:
        ranges = get_ranges_cached(acc)
    except Exception as e:
        _log("RANGE", f"akun #{acc['idx']}: {e}", Fore.YELLOW)
        return False

    def process_number(rng, num, fallback_country, code):
        full_num = normalize_number(num, code)
        if not full_num.isdigit():
            return False

        try:
            sms_list = get_sms(acc, rng, num)
        except Exception as e:
            _log("SMS", f"akun #{acc['idx']}: {e}", Fore.YELLOW)
            return False

        local_found = False
        for sms in sms_list:
            clean = re.sub(r"\s+", " ", sms.replace("<#>", "")).strip()
            uid   = hashlib.md5(f"{num}-{clean}".encode()).hexdigest()

            with _sent_cache_lock:
                if uid in sent_cache:
                    continue

            matches = _OTP_RE.findall(sms)
            if not matches:
                continue

            otp                       = re.sub(r"[^0-9]", "", matches[0])
            svc                       = detect_service(sms)
            country, flag, region_code = detect_country_and_flag(full_num, fallback_country)
            masked                    = mask_phone(full_num)

            msg = build_otp_message(otp, svc, flag, country, region_code, masked)
            tg_send_otp(otp, msg)
            cache_add(uid)

            _log(
                "OTP",
                f"{svc['icon']} {svc['name']:<10}  {flag} {region_code}  "
                f"{masked}  →  {otp}",
                Fore.GREEN,
            )
            local_found = True

        return local_found

    for rng in ranges:
        fallback_country, code = parse_range(rng)
        try:
            numbers = get_numbers(acc, rng)
        except Exception as e:
            _log("NUM", f"akun #{acc['idx']}: {e}", Fore.YELLOW)
            continue
        if not numbers:
            continue

        for n in numbers:
            try:
                if process_number(rng, n, fallback_country, code):
                    found = True
            except Exception as e:
                _log("NUM", f"akun #{acc['idx']}: {e}", Fore.YELLOW)
            time.sleep(0.5)

    return found
    

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ACCOUNT WORKER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def account_worker(acc):
    sleep_time = 2.0
    while True:
        try:
            found      = poll_one(acc)
            sleep_time = 1.0 if found else min(sleep_time + 0.5, POLL_INTERVAL_MAX)
        except Exception as e:
            _log("WORKER", f"akun #{acc['idx']}: {e}", Fore.RED)
            sleep_time = min(sleep_time * 2, 10.0)
        if sleep_time > 0:
            time.sleep(sleep_time)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# KEEPALIVE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_last_keepalive = {}

def keepalive_worker(accounts):
    _log("KEEPALIVE", f"aktif — ping tiap {KEEPALIVE_INTERVAL}s per akun", Fore.CYAN)
    while True:
        now = time.time()
        for acc in accounts:
            idx = acc["idx"]
            if now - _last_keepalive.get(idx, 0) < KEEPALIVE_INTERVAL:
                continue

            session_ok = False
            for _ in range(len(WORKER_POOL)):
                base = get_base()
                try:
                    r = acc["session"].get(f"{base}/portal", timeout=15)
                    if is_worker_blocked(r):
                        mark_worker_limited(base)
                        continue
                    if r.status_code == 200 and "/login" not in str(r.url):
                        _recv_csrf_cache.pop(idx, None)
                        _log("KA-OK", f"akun #{idx} — session aktif ✓", Fore.GREEN)
                        session_ok = True
                        break
                    if "/login" in str(r.url):
                        break
                except Exception as e:
                    _log("KA-ERR", f"{base}: {e}", Fore.YELLOW)
                    mark_worker_limited(base)

            if not session_ok:
                _log(
                    "KA-WARN",
                    f"akun #{idx} — session tidak terverifikasi. "
                    f"Update cookie.json & restart bot jika semua worker normal.",
                    Fore.YELLOW,
                )
                if OWNER_ID and OWNER_ID != DEFAULT_TARGET:
                    try:
                        _tg_post(OWNER_ID,
                            f"⚠️ <b>SESSION EXPIRED</b>\n\n"
                            f"Akun #{idx} tidak bisa akses portal IVAS.\n"
                            f"Perbarui <code>cookie.json</code> dengan cookie fresh "
                            f"dari browser, lalu restart bot.")
                    except:
                        pass

            _last_keepalive[idx] = now
            time.sleep(2)
        time.sleep(60)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HTTP HEALTH SERVER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_bot_start_time = time.time()

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path in ("", "/", "/health"):
            self._respond(200, "text/plain", b"OK")
        elif path == "/status":
            up   = int(time.time() - _bot_start_time)
            body = json.dumps({
                "status":         "running",
                "uptime_seconds": up,
                "uptime":         f"{up // 3600}h {(up % 3600) // 60}m {up % 60}s",
                "targets":        list_groups(),
            }).encode()
            self._respond(200, "application/json", body)
        else:
            self._respond(404, "text/plain", b"Not found")

    def _respond(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer.allow_reuse_address = True
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    _log("SERVER", f"port {port}  |  /health  /status", Fore.CYAN)
    server.serve_forever()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GRACEFUL SHUTDOWN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _shutdown(signum, frame):
    _log("SHUTDOWN", "menyimpan cache & keluar...", Fore.YELLOW)
    with _sent_cache_lock:
        save_sent_cache_now(sent_cache)
    _save_groups()
    _log("SHUTDOWN", "selesai.", Fore.YELLOW)
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    print(Fore.CYAN + Style.BRIGHT, end="")
    print("  ╔══════════════════════════════════════╗")
    print("  ║   🕷  SPIDERMAT OTP BOT              ║")
    print("  ║        FORWARD MODE                  ║")
    print("  ╚══════════════════════════════════════╝")
    print(Style.RESET_ALL)

    if not BOT_TOKEN:
        _log("FATAL", "BOT_TOKEN belum diset! Set via environment variable.", Fore.RED)
        sys.exit(1)

    _load_groups()

    cookies_list = load_cookies()
    if not cookies_list:
        _log("FATAL", f"Tidak ada cookie valid di {COOKIE_FILE}. Isi dulu!", Fore.RED)
        sys.exit(1)

    accounts = []
    for idx, ck in enumerate(cookies_list):
        acc = {
            "idx":        idx,
            "cookies":    ck,
            "session":    make_session(ck),
            "csrf_token": "",
        }
        accounts.append(acc)
        _log("COOKIE", f"Akun #{idx} — {len(ck)} cookie dimuat", Fore.GREEN)

    print()
    _log("CONFIG", f"Default target  →  {DEFAULT_TARGET}",         Fore.CYAN)
    _log("CONFIG", f"Total target    →  {len(list_groups())} grup", Fore.CYAN)
    _log("CONFIG", f"Channel link    →  {CHANNEL_LINK}",           Fore.CYAN)
    _log("CONFIG", f"Worker pool     →  {len(WORKER_POOL)} proxy",  Fore.CYAN)
    _log("CONFIG", f"Keepalive       →  tiap {KEEPALIVE_INTERVAL}s", Fore.CYAN)
    print()

    threading.Thread(target=run_health_server,                     daemon=True, name="health").start()
    threading.Thread(target=tg_update_listener,                    daemon=True, name="cmd-listener").start()
    threading.Thread(target=keepalive_worker, args=(accounts,),    daemon=True, name="keepalive").start()

    for acc in accounts:
        threading.Thread(
            target=account_worker, args=(acc,),
            daemon=True, name=f"poll-{acc['idx']}",
        ).start()
        _log("THREAD+", f"Akun #{acc['idx']} — polling aktif", Fore.GREEN)

    print()
    _log("CONFIG", "Bot berjalan. Ketik /addbot di grup untuk mendaftarkan.", Fore.CYAN)

    global _cache_dirty, _last_cache_save
    while True:
        if _cache_dirty and time.time() - _last_cache_save >= 5:
            with _sent_cache_lock:
                save_sent_cache_now(sent_cache)
            _last_cache_save = time.time()
            _cache_dirty     = False
        time.sleep(5)

main()
                
