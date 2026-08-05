import asyncio
import re
import requests
import phonenumbers
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
API_URL = "https://numberpanel.tech/api/otp?count=200"
POLL_INTERVAL = 10  # Seconds between API checks

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
        # Get flag emoji from country code
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
        InlineKeyboardButton(text="Methods", url="https://youtube.com/@xclusor", icon_custom_emoji_id="5807797645443340724"),
        InlineKeyboardButton(text="Channel", url="https://whatsapp.com/channel/0029VbC0kzIEFeXq9XLgHZ3y", icon_custom_emoji_id="5429571366384842791")
    ]
    row3 = [InlineKeyboardButton(text="OTP Panel", url="https://t.me/XclusoRPanelBot", icon_custom_emoji_id="5372917041193828849")]
    
    markup = InlineKeyboardMarkup([row1, row2, row3])
    
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
    
    print("🚀 Starting Forwarder Bot...")
    
    # Initial fetch to prevent sending old OTPs
    try:
        resp = requests.get(API_URL).json()
        for item in resp:
            uid = f"{item[0]}_{item[1]}_{item[3]}"
            seen_otps.add(uid)
        print(f"📦 Initialized with {len(seen_otps)} existing OTPs.")
    except Exception as e:
        print(f"⚠️ Initial API fetch failed: {e}")
        
    while True:
        try:
            resp = requests.get(API_URL).json()
            for item in reversed(resp):
                uid = f"{item[0]}_{item[1]}_{item[3]}"
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
