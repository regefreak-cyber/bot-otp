import logging
import sqlite3
import os
import re
import asyncio
import httpx
import hashlib
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from langdetect import detect

# ---- PTB Imports ----
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    CopyTextButton
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ---- Logging Configuration ----
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ---- Bot & Admin Configuration ----
BOT_NAME = "SPIDERMAT BOT"
BOT_TOKEN = "8879538187:AAGjRDdUdO6Iv50d3rKu_tCAcOwlVmBlg2k"
ADMIN_IDS = [6884022678]

# ---- IVAS Configuration ----
IVAS_EMAIL = "rahmatid27@gmail.com"
IVAS_PASSWORD = "Bangke123@"
IVAS_LOGIN_URL = "https://ivasms.com/login"
IVAS_BASE_URL = "https://ivasms.com/"
IVAS_API_ENDPOINT = "https://ivasms.com/portal/sms/received/getsms"

# ---- Service & Button Formatting Assets ----
SERVICE_ASSETS = {
    "WS": {"premium_id": "5334998226636390258", "fallback": "#WS"},
    "TG": {"premium_id": "5330237710655306682", "fallback": "#TG"},
    "FB": {"premium_id": "5323261730283863478", "fallback": "#FB"},
    "GO": {"premium_id": "5334998226636390258", "fallback": "#GO"},
}

BUTTON_ICONS = {
    "key": {"premium_id": "5231245436106318447", "fallback": "🔒"},
    "msg": {"premium_id": "5190859184312167965", "fallback": "💌"},
}

DEFAULT_OTP_CHANNEL = '-1003686221386'

# ---- Global State & Database Setup ----
IVAS_SESSION_CLIENT = None
PROCESSED_IDS = set()

def init_db():
    conn = sqlite3.connect('ivas_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS otp_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    number TEXT,
                    service TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

# ---- Helper Functions ----
def clean_number(phone):
    return re.sub(r'\D', '', str(phone))

def cool_otp_get(message):
    if not message:
        return "N/A"
    msg = str(message)
    msg = re.sub(r'https?://\S+', '', msg)
    keywords = ['code', 'otp', 'pin', 'kode', 'password', 'verification', 'auth', 'login']
    kw_pattern = '|'.join(keywords)
    
    m = re.search(rf'(?:{kw_pattern})[^\d]{{0,20}}?(\d{{3}}[- ]?\d{{3}}|\d{{4,8}})', msg, re.I)
    if m:
        return re.sub(r'[ -]', '', m.group(1))
    
    m = re.search(rf'(\d{{3}}[- ]?\d{{3}}|\d{{4,8}})[^\d]{{0,20}}?(?:{kw_pattern})', msg, re.I)
    if m:
        return re.sub(r'[ -]', '', m.group(1))
        
    for pat in [r'\d{4,8}', r'\d{3}[- ]\d{3}']:
        for match in re.finditer(pat, msg):
            digits = re.sub(r'[ -]', '', match.group(0))
            if 4 <= len(digits) <= 8:
                return digits
    return "N/A"

def get_short_service(sender_name):
    if not sender_name: return "OT"
    name = sender_name.upper()
    if "WHATSAPP" in name or "WS" in name: return "WS"
    if "FACEBOOK" in name or "FB" in name: return "FB"
    if "GOOGLE" in name or "GO" in name: return "GO"
    if "TELEGRAM" in name or "TG" in name: return "TG"
    return name[:2]

def detect_service(sender_name, message_text):
    full_text = f"{sender_name} {message_text}".lower()
    for svc in ['whatsapp', 'facebook', 'google', 'telegram', 'instagram', 'tiktok']:
        if svc in full_text:
            return svc.capitalize()
    return sender_name if sender_name else "Unknown"

def extract_csrf_token(html):
    soup = BeautifulSoup(html, 'html.parser')
    meta = soup.find('meta', {'name': 'csrf-token'})
    if meta and meta.get('content'):
        return meta['content']
    hidden = soup.find('input', {'name': re.compile(r'_token|csrf', re.I)})
    if hidden and hidden.get('value'):
        return hidden['value']
    return None

def format_public_message(number, service, message, otp):
    short_cli = get_short_service(service)
    asset = SERVICE_ASSETS.get(short_cli, {"premium_id": None, "fallback": f"#{short_cli}"})
    
    display_service = f'<tg-emoji emoji-id="{asset["premium_id"]}">📱</tg-emoji>' if asset.get("premium_id") else asset["fallback"]
    
    try:
        detected_lang = detect(message).upper()
    except:
        detected_lang = "UN"

    masked_num = f"{number[:3]}★★★★{number[-4:]}" if len(number) > 7 else number
    text = f"🌐 {display_service} <code>{masked_num}</code> #{detected_lang}"

    keyboard = [
        [
            InlineKeyboardButton(
                text=f"{BUTTON_ICONS['key']['fallback']} {otp}", 
                copy_text=CopyTextButton(text=otp),
                api_kwargs={"style": "success", "icon_custom_emoji_id": BUTTON_ICONS['key']['premium_id']}
            ),
            InlineKeyboardButton(
                text=f"{BUTTON_ICONS['msg']['fallback']} Message",
                copy_text=CopyTextButton(text=message),
                api_kwargs={"style": "danger", "icon_custom_emoji_id": BUTTON_ICONS['msg']['premium_id']}
            )
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)

# ---- IVAS Core Engine ----
async def ivas_fetch_sms(client: httpx.AsyncClient, headers: dict, csrf_token: str):
    all_messages = []
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        payload_range = {'from': yesterday, 'to': today, '_token': csrf_token}
        resp_range = await client.post(IVAS_API_ENDPOINT, data=payload_range, headers=headers)
        if resp_range.status_code != 200:
            return []

        soup_range = BeautifulSoup(resp_range.text, 'html.parser')
        ranges = []
        for div in soup_range.find_all('div', onclick=True):
            onclick = div.get('onclick')
            if 'toggleRange' in onclick:
                try:
                    ranges.append(onclick.split("'")[1])
                except:
                    pass
        ranges = list(set(ranges))

        numbers_url = f"{IVAS_BASE_URL}portal/sms/received/getsms/number"
        sms_url = f"{IVAS_BASE_URL}portal/sms/received/getsms/number/sms"
        semaphore = asyncio.Semaphore(3)

        async def fetch_numbers(rng):
            async with semaphore:
                payload = {'start': yesterday, 'end': today, 'range': rng, '_token': csrf_token}
                res = await client.post(numbers_url, data=payload, headers=headers)
                if res.status_code != 200: return []
                soup = BeautifulSoup(res.text, 'html.parser')
                nums = []
                for div in soup.find_all('div', onclick=True):
                    try:
                        n = div.get('onclick').split("'")[1]
                        if n and n != rng: nums.append(n)
                    except: pass
                return list(set(nums))

        numbers_per_range = await asyncio.gather(*[fetch_numbers(r) for r in ranges])
        all_numbers = [(r, n) for r, nums in zip(ranges, numbers_per_range) for n in nums]

        async def fetch_sms(rng, num):
            async with semaphore:
                payload = {'start': yesterday, 'end': today, 'Number': num, 'Range': rng, '_token': csrf_token}
                res = await client.post(sms_url, data=payload, headers=headers)
                if res.status_code != 200: return []
                soup = BeautifulSoup(res.text, 'html.parser')
                
                sms_texts = [p.get_text(strip=True) for p in soup.find_all('p')] or soup.get_text(separator='\n', strip=True).split('\n')
                msgs = []
                for sms in sms_texts:
                    if not sms or len(sms) < 5 or re.match(r'^\d{1,2}:\d{2}', sms.strip()):
                        continue
                    otp = cool_otp_get(sms)
                    if otp == "N/A": continue
                    
                    svc = detect_service("", sms)
                    uid = hashlib.md5(f"{num}-{sms}".encode()).hexdigest()
                    msgs.append({
                        "id": uid, "number": num, "full_sms": sms, 
                        "code": otp, "service": svc
                    })
                return msgs

        sms_results = await asyncio.gather(*[fetch_sms(r, n) for r, n in all_numbers])
        for msgs in sms_results:
            all_messages.extend(msgs)

        return all_messages
    except Exception as e:
        logger.error(f"IVAS Fetch Error: {e}")
        return []

async def ivas_monitoring_task(app):
    global IVAS_SESSION_CLIENT
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    if IVAS_SESSION_CLIENT is None:
        IVAS_SESSION_CLIENT = httpx.AsyncClient(timeout=40.0, follow_redirects=True, headers=headers)

        while True:
        try:
            logger.info("Connecting to IVAS Login...")
            resp = await IVAS_SESSION_CLIENT.get(IVAS_LOGIN_URL)
            logger.info(f"Response Status: {resp.status_code}")
            
            token = extract_csrf_token(resp.text)
            if not token:
                logger.error("Gagal dapet CSRF Token!")
                await asyncio.sleep(10)
                continue

            logger.info(f"CSRF Token dapet: {token[:10]}...")

            # --- [TAMBAHKAN BAGIAN INI: PROSES KIRIM USERNAME & PASSWORD] ---
            login_payload = {
                "username": IVAS_USERNAME,
                "password": IVAS_PASSWORD,
                "_token": token  # Sesuaikan nama key token jika beda (misal: 'csrf_token')
            }

            login_resp = await IVAS_SESSION_CLIENT.post(IVAS_LOGIN_URL, data=login_payload)
            logger.info(f"Login Status Code: {login_resp.status_code}")
            logger.info("Login successful, fetching dashboard...")
            # -----------------------------------------------------------------

            # Setelah berhasil login, barulah masuk ke loop narik SMS
            while True:
                messages = await ivas_fetch_sms(IVAS_SESSION_CLIENT, headers, ...)
                
                    
                    num = msg.get('number')
                    sms = msg.get('full_sms')
                    otp = msg.get('code')
                    svc = msg.get('service')

                    text_pub, markup_pub = format_public_message(num, svc, sms, otp)

                    # Send to Telegram OTP Channel
                    try:
                        await app.bot.send_message(
                            chat_id=DEFAULT_OTP_CHANNEL,
                            text=text_pub,
                            parse_mode=ParseMode.HTML,
                            reply_markup=markup_pub
                        )
                        logger.info(f"Broadcasted OTP for number: {num}")
                    except Exception as err:
                        logger.error(f"Broadcast Error: {err}")

                    PROCESSED_IDS.add(sms_id)

                await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"IVAS Monitor Critical Exception: {e}")
            IVAS_SESSION_CLIENT = None
            await asyncio.sleep(10)

# ---- Telegram Commands ----
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ **IVAS Monitoring Bot Active**\n\n"
        "Bot secara otomatis menyadap dan membagikan OTP dari panel IVASMS ke Channel.",
        parse_mode=ParseMode.MARKDOWN
    )

# ---- Main Entry Point ----
async def post_init(application):
    asyncio.create_task(ivas_monitoring_task(application))
    
def main():
    init_db()
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start_cmd))

    logger.info("Bot IVAS running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
