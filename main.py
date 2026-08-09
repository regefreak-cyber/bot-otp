"""
SPIDERMAT OTP BOT — TARGETED MONITORING MODE
Command:
  /addbot /removebot /listbot (Manajemen Grup Target)
  /addnum /delnum /listnum /clearnum (Manajemen Nomor Terpantau)
  Atau langsung KIRIM FILE .TXT isi nomor-nomor ke chat bot Telegram!
"""

import os
import re
import sys
import json
import time
import signal
import hashlib
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import httpx
import requests
from bs4 import BeautifulSoup
from colorama import init, Fore, Style

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
init(autoreset=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
OWNER_ID       = int(os.getenv("OWNER_ID", "0"))
DEFAULT_TARGET = -1003686221386

COOKIE_FILE  = "cookie.json"
CACHE_FILE   = "file/sent_cache.json"
GROUPS_FILE  = "file/groups.json"
TARGET_NUMS_FILE = "file/target_numbers.json"

POLL_INTERVAL = 2.0  # Jeda polling cepat karena request sangat sedikit!
MAX_CACHE     = 2000

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LOGGING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _log(tag, msg, color=Fore.CYAN):
    ts = datetime.now().strftime("%H:%M:%S")
    print(color + f"  {ts}  [{tag:<8}]  {msg}" + Style.RESET_ALL, flush=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TARGET NUMBERS MANAGEMENT (.TXT & JSON)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_target_nums_lock = threading.Lock()
_active_numbers: dict = {}  # format: {"628xxx": {"range": "INDONESIA (62)"}}

def load_target_numbers():
    os.makedirs("file", exist_ok=True)
    if not os.path.exists(TARGET_NUMS_FILE):
        return
    try:
        with open(TARGET_NUMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                with _target_nums_lock:
                    _active_numbers.update(data)
        _log("NUMS", f"Berhasil memuat {len(_active_numbers)} nomor terget.", Fore.GREEN)
    except Exception as e:
        _log("NUMS", f"Error load target numbers: {e}", Fore.RED)

def save_target_numbers():
    try:
        os.makedirs("file", exist_ok=True)
        with _target_nums_lock:
            data = dict(_active_numbers)
        with open(TARGET_NUMS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        _log("NUMS", f"Error save target numbers: {e}", Fore.RED)

def add_target_number(num_str: str) -> bool:
    clean_num = re.sub(r"\D", "", str(num_str))
    if len(clean_num) < 6:
        return False
    with _target_nums_lock:
        if clean_num not in _active_numbers:
            _active_numbers[clean_num] = {"added_at": time.time()}
            save_target_numbers()
            return True
    return False

def clear_target_numbers():
    with _target_nums_lock:
        _active_numbers.clear()
        save_target_numbers()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# IVAS SESSION & WORKER POOL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WORKER_POOL = [
    "https://plain-butterfly-d9e9.kicenivas.workers.dev",
    "https://ivasmunchen.serverprivate1.web.id",
    "https://ivasmsbykicenv2.kikixrakaofficial.biz.id",
    "https://ivasbykiven.alwayskixyzshop.web.id",
]

_worker_idx = 0
def get_base():
    return WORKER_POOL[_worker_idx % len(WORKER_POOL)]

def load_cookies():
    if not os.path.exists(COOKIE_FILE):
        return []
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [{x["name"]: x["value"] for x in data}] if "name" in data[0] else data
            return [data]
    except:
        return []

def make_session(cookies: dict):
    hdrs = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
    s = httpx.Client(follow_redirects=True, timeout=15, headers=hdrs)
    s.cookies.update(cookies)
    return s

def get_recv_csrf(acc) -> str:
    base = get_base()
    try:
        r = acc["session"].get(f"{base}/portal/sms/received", timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        meta = soup.find("meta", {"name": "csrf-token"})
        return meta.get("content", "") if meta else ""
    except:
        return ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OTP & MESSAGE BUILDER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_OTP_RE = re.compile(r"\b\d{3}[-\s]?\d{3}\b|\b\d{4,8}\b")

def build_otp_message(otp: str, flag: str, region_code: str, num_str: str) -> str:
    raw_num = re.sub(r"\D", "", num_str)
    phone_formatted = f"<b>{raw_num[:4]}•SPDRMT•{raw_num[-4:]}</b>" if len(raw_num) >= 8 else f"<b>{raw_num}</b>"
    prefix = raw_num[:6] if len(raw_num) >= 6 else raw_num

    return (
        f"¤ {flag} <b>{region_code}</b> ¤ {phone_formatted} ¤\n\n"
        f"<b>Prefix:</b> <tg-spoiler>{prefix}</tg-spoiler>"
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TELEGRAM BOT & FILE LISTENER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_tg_session = requests.Session()

def tg_send_msg(chat_id: int, text: str):
    try:
        _tg_session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": "HTML"
        }, timeout=10)
    except:
        pass

def tg_send_otp(otp: str, msg_text: str):
    kb = {"inline_keyboard": [[{"text": f"{otp}", "copy_text": {"text": otp}}], [{"text": "All Files", "url": "https://t.me/matchaappp"}]]}
    try:
        _tg_session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
            "chat_id": DEFAULT_TARGET, "text": msg_text, "parse_mode": "HTML", "reply_markup": kb
        }, timeout=10)
    except Exception as e:
        _log("TG-ERR", f"Gagal kirim OTP: {e}", Fore.RED)

def handle_command_and_files(update: dict):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    chat_id = msg.get("chat", {}).get("id")
    text    = (msg.get("text") or "").strip()
    doc     = msg.get("document")

    # 1. HANDLE UPLOAD FILE .TXT
    if doc:
        file_name = doc.get("file_name", "")
        if file_name.endswith(".txt"):
            file_id = doc.get("file_id")
            tg_send_msg(chat_id, "⏳ <i>Mendownload & memproses file nomor...</i>")
            try:
                # Get File Path
                r = _tg_session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}").json()
                file_path = r.get("result", {}).get("file_path")
                # Download File Content
                file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
                content  = _tg_session.get(file_url).text
                
                added_count = 0
                for line in content.splitlines():
                    num = re.sub(r"\D", "", line)
                    if len(num) >= 6:
                        if add_target_number(num):
                            added_count += 1

                tg_send_msg(chat_id, f"✅ <b>BERHASIL!</b>\nMenambahkan <b>{added_count}</b> nomor baru dari file <code>{file_name}</code>.")
                _log("NUMS", f"Added {added_count} numbers from file {file_name}", Fore.GREEN)
            except Exception as e:
                tg_send_msg(chat_id, f"❌ Gagal memproses file: {e}")
        return

    # 2. HANDLE COMMANDS
    cmd = text.split()[0].lower() if text.startswith("/") else ""

    if cmd == "/addnum":
        parts = text.split()
        if len(parts) > 1:
            num = parts[1]
            if add_target_number(num):
                tg_send_msg(chat_id, f"✅ Nomor <code>{num}</code> ditambahkan ke daftar pantaun.")
            else:
                tg_send_msg(chat_id, "⚠️ Nomor tidak valid atau sudah ada.")
        else:
            tg_send_msg(chat_id, "Gunakan: <code>/addnum 628xxxx</code>")

    elif cmd == "/listnum":
        with _target_nums_lock:
            total = len(_active_numbers)
            nums  = list(_active_numbers.keys())[:20]
        preview = "\n".join([f"• <code>{n}</code>" for n in nums])
        tg_send_msg(chat_id, f"📱 <b>TOTAL NOMOR DIPANTAU: {total}</b>\n\n{preview}\n\n<i>(Menampilkan max 20 nomor)</i>")

    elif cmd == "/clearnum":
        clear_target_numbers()
        tg_send_msg(chat_id, "🗑️ Semua daftar nomor terpantau berhasil dibersihkan!")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POLLING TARGETED NUMBERS ONLY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
sent_cache = set()

def poll_target_numbers(acc):
    base = get_base()
    csrf = get_recv_csrf(acc)
    today = datetime.now().strftime("%Y-%m-%d")

    with _target_nums_lock:
        nums_to_check = list(_active_numbers.keys())

    if not nums_to_check:
        return

    for num in nums_to_check:
        try:
            r = acc["session"].post(
                f"{base}/portal/sms/received/getsms/number/sms",
                data={"_token": csrf, "start": today, "end": today, "Number": num, "Range": ""},
                headers={"Referer": f"{base}/portal/sms/received", "X-Requested-With": "XMLHttpRequest"},
                timeout=10
            )
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            cells = soup.find_all(["td", "div"], class_=re.compile(r"message|sms", re.I)) or [soup]
            
            for cell in cells:
                sms_text = cell.get_text(separator=" ").strip().replace("<#>", "")
                if not sms_text or "No SMS Found" in sms_text:
                    continue

                uid = hashlib.md5(f"{num}-{sms_text}".encode()).hexdigest()
                if uid in sent_cache:
                    continue

                matches = _OTP_RE.findall(sms_text)
                if matches:
                    raw_otp = matches[0]
                    clean_otp = re.sub(r"\D", "", raw_otp)
                    
                    # Send to Telegram
                    msg = build_otp_message(clean_otp, "🇲🇨", "ID", num)
                    tg_send_otp(clean_otp, msg)
                    
                    sent_cache.add(uid)
                    _log("OTP", f"SMS DITERIMA [{num}] → {clean_otp}", Fore.GREEN)

        except Exception as e:
            pass
        time.sleep(0.5)

def worker_loop(acc):
    while True:
        try:
            poll_target_numbers(acc)
        except Exception as e:
            _log("WORKER", f"Error: {e}", Fore.RED)
        time.sleep(POLL_INTERVAL)

def tg_listener_loop():
    offset = 0
    while True:
        try:
            r = _tg_session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", json={"offset": offset, "timeout": 20}).json()
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1
                handle_command_and_files(upd)
        except:
            time.sleep(3)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN EXECUTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    _log("START", "Menjalankan SPIDERMAT OTP BOT (Targeted Mode)", Fore.CYAN)
    
    load_target_numbers()
    cookies = load_cookies()
    if not cookies:
        _log("FATAL", "Cookie tidak ditemukan di cookie.json!", Fore.RED)
        sys.exit(1)

    acc = {"session": make_session(cookies[0])}

    # Start Telegram Updates Listener
    threading.Thread(target=tg_listener_loop, daemon=True).start()
    
    # Start Worker Loop
    threading.Thread(target=worker_loop, args=(acc,), daemon=True).start()

    _log("READY", "Bot Siap! Kirim file .txt ke Telegram bot untuk mulai memantau nomor.", Fore.GREEN)

    while True:
        time.sleep(10)

if __name__ == "__main__":
    main()
            
