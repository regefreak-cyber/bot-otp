import asyncio
import json
import re
import requests
import phonenumbers
from bs4 import BeautifulSoup
from phonenumbers import geocoder
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode

try:
    from telegram import CopyTextButton
except ImportError:
    CopyTextButton = None

# === CONFIGURATION ===
BOT_TOKEN = "8879538187:AAFDavorTbeRYQoQbMY-4mDcTI1d1GMHVlc"
GROUP_ID = -1003686221386
POLL_INTERVAL = 10  # Detik jeda per cek API

# Worker IVAS Proxy
WORKER_URL = "https://plain-butterfly-d9e9.kicenivas.workers.dev"

# Emojis for services
APP_EMOJIS = {
    "whatsapp": "💬",
    "telegram": "✈️",
    "facebook": "📘",
    "instagram": "📸",
    "tiktok": "🎵",
    "google": "🌐",
    "twitter": "🐦"
}

def get_app_emoji(service_name):
    service_name = str(service_name).lower()
    for key, emoji in APP_EMOJIS.items():
        if key in service_name:
            return emoji
    return "📱"

def get_country_info(phone_number):
    if not phone_number.startswith('+'):
        phone_number = '+' + phone_number
    try:
        parsed = phonenumbers.parse(phone_number)
        country_name = geocoder.country_name_for_number(parsed, "en") or "Unknown"
        region = phonenumbers.region_code_for_number(parsed)
        if region:
            flag = chr(ord(region[0]) + 127397) + chr(ord(region[1]) + 127397)
        else:
            flag = "🏳️"
        iso = region or "UN"
        return country_name, flag, iso
    except:
        return "Unknown", "🏳️", "UN"

def extract_otp(msg):
    otp_match = re.search(r'\d{3}[-\s]?\d{3,4}|\d{4,8}', msg)
    return otp_match.group(0) if otp_match else 'Unknown'

def mask_number(num):
    num = str(num).replace('+', '')
    if len(num) <= 6:
        return num
    return num[:3] + "x" * (len(num) - 6) + num[-3:]

# === FUNGSI OPSI B: NARIK DATA DARI IVAS ===
def fetch_ivas_otps():
    otps = []
    session = requests.Session()

    # BACA DAN PAKSA PASANG COOKIE
    try:
        with open("cookie.json", "r", encoding="utf-8") as f:
            cookie_data = json.load(f)
            if isinstance(cookie_data, list):
                for item in cookie_data:
                    if "name" in item and "value" in item:
                        session.cookies.set(item["name"], item["value"])
            elif isinstance(cookie_data, dict):
                for k, v in cookie_data.items():
                    session.cookies.set(k, v)
    except Exception as e:
        print(f"⚠️ Error membaca cookie.json: {e}")
        return otps

    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{WORKER_URL}/portal/sms/received"
    })

    try:
        # 1. Ambil CSRF Token
        r = session.get(f"{WORKER_URL}/portal/sms/received")
        soup = BeautifulSoup(r.text, "html.parser")
        meta = soup.find("meta", {"name": "csrf-token"})
        csrf = meta.get("content", "") if meta else ""

        # 2. Ambil Range Negara
        r_range = session.post(
            f"{WORKER_URL}/portal/sms/received/getsms",
            data={"_token": csrf, "from": "today", "to": "today"}
        )
        soup_range = BeautifulSoup(r_range.text, "html.parser")
        ranges = []
        for div in soup_range.find_all("div", onclick=True):
            if "toggleRange" in div.get("onclick", ""):
                try:
                    ranges.append(div["onclick"].split("'")[1])
                except Exception:
                    pass

        # 3. Ambil Nomor HP & SMS
        for rng in list(set(ranges))[:3]:
            r_num = session.post(
                f"{WORKER_URL}/portal/sms/received/getsms/number",
                data={"start": "today", "end": "today", "range": rng}
            )
            soup_num = BeautifulSoup(r_num.text, "html.parser")
            for div in soup_num.find_all("div", onclick=True):
                try:
                    num = div["onclick"].split("'")[1]
                    if num and num != rng:
                        r_sms = session.post(
                            f"{WORKER_URL}/portal/sms/received/getsms/number",
                            data={"range": rng, "number": num}
                        )
                        sms_data = r_sms.json()
                        sms_list = sms_data if isinstance(sms_data, list) else sms_data.get("sms", [])
                        
                        for sms in sms_list[:1]:
                            clean_msg = str(sms)
                            m = re.search(r"(WhatsApp|Telegram|Google|Facebook|Instagram|TikTok|Twitter)", clean_msg, re.I)
                            svc = m.group(1) if m else "OTP"
                            otps.append([svc, num, clean_msg])
                except Exception:
                    pass
    except Exception as e:
        print(f"⚠️ Error fetch IVAS: {e}")

    return otps
                            
async def send_to_group(bot, entry):
    service = entry[0]
    num = entry[1]
    msg = entry[2]
    
    country_name, flag, iso = get_country_info(num)
    app_emoji = get_app_emoji(service)
    masked = mask_number(num)
    otp = extract_otp(msg)
    
    text = f"{flag} <b>#{iso} {app_emoji}{service} {masked}</b> <tg-emoji emoji-id=\"5264919878082509254\">▶️</tg-emoji>"
    
    if CopyTextButton:
        try:
            row1 = [InlineKeyboardButton(text=f"{otp}", copy_text=CopyTextButton(text=otp), icon_custom_emoji_id="6176966310920983412")]
        except:
            row1 = [InlineKeyboardButton(text=f"🔑 {otp}", callback_data="noop")]
    else:
        row1 = [InlineKeyboardButton(text=f"🔑 {otp}", callback_data="noop")]
        
    row2 = [
        InlineKeyboardButton(text="Channel", url="https://t.me/matchaappp", icon_custom_emoji_id="5429571366384842791")
    ]
    
    markup = InlineKeyboardMarkup([row1, row2])
    
    try:
        await bot.send_message(
            chat_id=GROUP_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True
        )
        print(f"✅ Sent OTP for {num} - {service}")
    except Exception as e:
        print(f"❌ Failed to send to group: {e}")

async def main():
    bot = Bot(token=BOT_TOKEN)
    seen_otps = set()
    
    print("🚀 Starting Forwarder Bot (IVAS Mode)...")
    
    # Warmup awal
    try:
        resp = fetch_ivas_otps()
        for item in resp:
            uid = f"{item[0]}_{item[1]}_{item[2]}"
            seen_otps.add(uid)
        print(f"📦 Initialized with {len(seen_otps)} existing OTPs.")
    except Exception as e:
        print(f"⚠️ Initial fetch failed: {e}")
        
    while True:
        try:
            resp = fetch_ivas_otps()
            for item in reversed(resp):
                uid = f"{item[0]}_{item[1]}_{item[2]}"
                if uid not in seen_otps:
                    seen_otps.add(uid)
                    await send_to_group(bot, item)
                    await asyncio.sleep(0.5)
                    
            if len(seen_otps) > 10000:
                seen_otps = set(list(seen_otps)[-5000:])
                
        except Exception as e:
            print(f"⚠️ Error fetching API: {e}")
            
        await asyncio.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
        
