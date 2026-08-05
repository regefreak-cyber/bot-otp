import logging
import sqlite3
import time
import os
import re
import threading
import sys
import httpx
import hashlib
import random
import zipfile
import io
import asyncio
from datetime import datetime, timedelta
from io import BytesIO
from bs4 import BeautifulSoup
from telegram import CopyTextButton
import json
from langdetect import detect, detect_langs, DetectorFactory
import PyPDF2
from urllib.parse import urljoin
from collections import Counter
# ---- PTB Imports ----
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import BadRequest

# ---- Main Configuration ----
BOT_NAME = "SPIDERMAT BOT"
DB_FILE = "numbers.db"


# ---- Configure Logging ----
os.environ['PYTHONIOENCODING'] = 'utf-8'
STATE_FILE = "ivas_sms_history.json"
ACCOUNTS_FILE = "panel_accounts.json"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)

BOT_TOKEN = "8879538187:AAFDavorTbeRYQoQbMY-4mDcTI1d1GMHVlc"
ADMIN_IDS = [6884022678]


# ---- Ivas Configuration ----
IVAS_EMAIL = "rahmatid27@gmail.com"
IVAS_PASSWORD = "Bangke123@"
IVAS_LOGIN_URL = "https://ivasms.com/login"
IVAS_BASE_URL = "https://ivasms.com/"
IVAS_API_ENDPOINT = "https://ivasms.com/portal/sms/received/getsms"

# ---- Service Keywords for Ivas ----
SERVICE_KEYWORDS = {
    "WhatsApp": ["Whatsapp", "ws", "whatsapp"],
    "Telegram": ["telegram", "tg"],
    "Google": ["google", "gg", "youtube"],
    "Facebook": ["facebook", "fb"],
    "TikTok": ["tiktok"],
    "Instagram": ["instagram", "ig"]
}

SERVICE_ASSETS = {
    "WS": {"premium_id": "5334998226636390258", "fallback": "#WS"},
    "TG": {"premium_id": "5330237710655306682", "fallback": "#TG"},
    "FB": {"premium_id": "5323261730283863478", "fallback": "#FB"},
    "GO": {"premium_id": "5334998226636390258", "fallback": "#GO"},
}

BUTTON_ICONS = {
    "key": {"premium_id": "5231245436106318447", "fallback": "🔒"},
    "msg": {"premium_id": "5190859184312167965", "fallback": "💌"},
    "bell": {"premium_id": "6312169686670773914", "fallback": "📱"},
}

# ---- Premium Flags ----
try:
    with open("premium_flags.json", "r", encoding="utf-8") as _pf:
        PREMIUM_FLAGS = json.load(_pf)
except Exception:
    PREMIUM_FLAGS = {}

def get_premium_flag(flag_emoji: str) -> str:
    """Return tg-emoji tag for premium flag, fallback to original emoji."""
    emoji_id = PREMIUM_FLAGS.get(flag_emoji) or PREMIUM_FLAGS.get(flag_emoji.rstrip("\ufe0f"))
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{flag_emoji}</tg-emoji>'
    return flag_emoji

# --- Multiple Account
DEFAULT_ACCOUNTS = [
    {
        "username": "gombong123",
        "password": "bangke123",
        "base_url": "http://smshadi.net/agent/SMSDashboard",
        "login_path": "/login",
        "signin_path": "/signin",
        "api_path": "/client/res/data_smscdr.php"
    },
    {
        "username": "akunclient",
        "password": "akunclient",
        "base_url": "http://139.99.9.4/ints",
        "login_path": "/login",
        "signin_path": "/signin",
        "api_path": "/client/res/data_smscdr.php"
     },   
]   
#  --- Default Channel Configuration ---
DEFAULT_MAIN_CHANNEL = 'https://t.me/matchaappp'
DEFAULT_BACKUP_CHANNEL = '-1003686221386'
DEFAULT_BACKUP_CHANNEL_LINK = 'https://t.me/matchaappp'
OTP_LINK = 'https://t.me/+e-fBEeAkjPcyNjg1'
DEFAULT_OTP_CHANNEL = '-1003686221386'

# --- Global variables ---
stop_event = threading.Event()
reported_sms_hashes_cache = set()
USER_STATE = {}
working_api_url = None
MAIN_LOOP = None
GLOBAL_APP = None
app_instance = None
application_bot = None
telegram_lock = asyncio.Semaphore(3)
IVAS_SESSION_CLIENT = None


# --- Reference Data 
COUNTRY_CODES = {
    '1': ('USA/Canada', '🇺🇸', 'US'), '79': ('Russia', '🇷🇺', 'RU'), '20': ('Egypt', '🇪🇬', 'EG'), '27': ('South Africa', '🇿🇦', 'ZA'),
    '30': ('Greece', '🇬🇷', 'GR'), '31': ('Netherlands', '🇳🇱', 'NL'), '32': ('Belgium', '🇧🇪', 'BE'), '33': ('France', '🇫🇷', 'FR'),
    '34': ('Spain', '🇪🇸', 'ES'), '36': ('Hungary', '🇭🇺', 'HU'), '39': ('Italy', '🇮🇹', 'IT'), '40': ('Romania', '🇷🇴', 'RO'),
    '41': ('Switzerland', '🇨🇭', 'CH'), '43': ('Austria', '🇦🇹', 'AT'), '44': ('United Kingdom', '🇬🇧', 'GB'), '45': ('Denmark', '🇩🇰', 'DK'),
    '46': ('Sweden', '🇸🇪', 'SE'), '47': ('Norway', '🇳🇴', 'NO'), '48': ('Poland', '🇵🇱', 'PL'), '49': ('Germany', '🇩🇪', 'DE'),
    '51': ('Peru', '🇵🇪', 'PE'), '52': ('Mexico', '🇲🇽', 'MX'), '53': ('Cuba', '🇨🇺', 'CU'), '54': ('Argentina', '🇦🇷', 'AR'),
    '55': ('Brazil', '🇧🇷', 'BR'), '56': ('Chile', '🇨🇱', 'CL'), '57': ('Colombia', '🇨🇴', 'CO'), '58': ('Venezuela', '🇻🇪', 'VE'),
    '60': ('Malaysia', '🇲🇾', 'MY'), '61': ('Australia', '🇦🇺', 'AU'), '62': ('Indonesia', '🇮🇩', 'ID'), '63': ('Philippines', '🇵🇭', 'PH'),
    '64': ('New Zealand', '🇳🇿', 'NZ'), '65': ('Singapore', '🇸🇬', 'SG'), '66': ('Thailand', '🇹🇭', 'TH'), '81': ('Japan', '🇯🇵', 'JP'),
    '82': ('South Korea', '🇰🇷', 'KR'), '84': ('Viet Nam', '🇻🇳', 'VN'), '86': ('China', '🇨🇳', 'CN'), '90': ('Turkey', '🇹🇷', 'TR'),
    '91': ('India', '🇮🇳', 'IN'), '92': ('Pakistan', '🇵🇰', 'PK'), '93': ('Afghanistan', '🇦🇫', 'AF'), '94': ('Sri Lanka', '🇱🇰', 'LK'),
    '95': ('Myanmar', '🇲🇲', 'MM'), '98': ('Iran', '🇮🇷', 'IR'), '211': ('South Sudan', '🇸🇸', 'SS'), '212': ('Morocco', '🇲🇦', 'MA'),
    '213': ('Algeria', '🇩🇿', 'DZ'), '216': ('Tunisia', '🇹🇳', 'TN'), '218': ('Libya', '🇱🇾', 'LY'), '220': ('Gambia', '🇬🇲', 'GM'),
    '221': ('Senegal', '🇸🇳', 'SN'), '222': ('Mauritania', '🇲🇷', 'MR'), '223': ('Mali', '🇲🇱', 'ML'), '224': ('Guinea', '🇬🇳', 'GN'),
    '225': ("Côte d'Ivoire", '🇨🇮', 'CI'), '226': ('Burkina Faso', '🇧🇫', 'BF'), '227': ('Niger', '🇳🇪', 'NE'), '228': ('Togo', '🇹🇬', 'TG'),
    '229': ('Benin', '🇧🇯', 'BJ'), '230': ('Mauritius', '🇲🇺', 'MU'), '231': ('Liberia', '🇱🇷', 'LR'), '232': ('Sierra Leone', '🇸🇱', 'SL'),
    '233': ('Ghana', '🇬🇭', 'GH'), '234': ('Nigeria', '🇳🇬', 'NG'), '235': ('Chad', '🇹🇩', 'TD'), '236': ('Central African Republic', '🇨🇫', 'CF'),
    '237': ('Cameroon', '🇨🇲', 'CM'), '238': ('Cape Verde', '🇨🇻', 'CV'), '239': ('Sao Tome and Principe', '🇸🇹', 'ST'),
    '240': ('Equatorial Guinea', '🇬🇶', 'GQ'), '241': ('Gabon', '🇬🇦', 'GA'), '242': ('Congo', '🇨🇬', 'CG'),
    '243': ('DR Congo', '🇨🇩', 'CD'), '244': ('Angola', '🇦🇴', 'AO'), '245': ('Guinea-Bissau', '🇬🇼', 'GW'), '248': ('Seychelles', '🇸🇨', 'SC'),
    '249': ('Sudan', '🇸🇩', 'SD'), '250': ('Rwanda', '🇷🇼', 'RW'), '251': ('Ethiopia', '🇪🇹', 'ET'), '252': ('Somalia', '🇸🇴', 'SO'),
    '253': ('Djibouti', '🇩🇯', 'DJ'), '254': ('Kenya', '🇰🇪', 'KE'), '255': ('Tanzania', '🇹🇿', 'TZ'), '256': ('Uganda', '🇺🇬', 'UG'),
    '257': ('Burundi', '🇧🇮', 'BI'), '258': ('Mozambique', '🇲🇿', 'MZ'), '260': ('Zambia', '🇿🇲', 'ZM'), '261': ('Madagascar', '🇲🇬', 'MG'),
    '263': ('Zimbabwe', '🇿🇼', 'ZW'), '264': ('Namibia', '🇳🇦', 'NA'), '265': ('Malawi', '🇲🇼', 'MW'), '266': ('Lesotho', '🇱🇸', 'LS'),
    '267': ('Botswana', '🇧🇼', 'BW'), '268': ('Eswatini', '🇸🇿', 'SZ'), '269': ('Comoros', '🇰🇲', 'KM'), '290': ('Saint Helena', '🇸🇭', 'SH'),
    '291': ('Eritrea', '🇪🇷', 'ER'), '297': ('Aruba', '🇦🇼', 'AW'), '298': ('Faroe Islands', '🇫🇴', 'FO'), '299': ('Greenland', '🇬🇱', 'GL'),
    '350': ('Gibraltar', '🇬🇮', 'GI'), '351': ('Portugal', '🇵🇹', 'PT'), '352': ('Luxembourg', '🇱🇺', 'LU'), '353': ('Ireland', '🇮🇪', 'IE'),
    '354': ('Iceland', '🇮🇸', 'IS'), '355': ('Albania', '🇦🇱', 'AL'), '356': ('Malta', '🇲🇹', 'MT'), '357': ('Cyprus', '🇨🇾', 'CY'),
    '358': ('Finland', '🇫🇮', 'FI'), '359': ('Bulgaria', '🇧🇬', 'BG'), '370': ('Lithuania', '🇱🇹', 'LT'), '371': ('Latvia', '🇱🇻', 'LV'),
    '372': ('Estonia', '🇪🇪', 'EE'), '373': ('Moldova', '🇲🇩', 'MD'), '374': ('Armenia', '🇦🇲', 'AM'), '375': ('Belarus', '🇧🇾', 'BY'),
    '376': ('Andorra', '🇦🇩', 'AD'), '377': ('Monaco', '🇲🇨', 'MC'), '378': ('San Marino', '🇸🇲', 'SM'), '380': ('Ukraine', '🇺🇦', 'UA'),
    '381': ('Serbia', '🇷🇸', 'RS'), '382': ('Montenegro', '🇲🇪', 'ME'), '385': ('Croatia', '🇭🇷', 'HR'), '386': ('Slovenia', '🇸🇮', 'SI'),
    '387': ('Bosnia and Herzegovina', '🇧🇦', 'BA'), '389': ('North Macedonia', '🇲🇰', 'MK'), '420': ('Czech Republic', '🇨🇿', 'CZ'),
    '421': ('Slovakia', '🇸🇰', 'SK'), '423': ('Liechtenstein', '🇱🇮', 'LI'), '501': ('Belize', '🇧🇿', 'BZ'), '502': ('Guatemala', '🇬🇹', 'GT'),
    '503': ('El Salvador', '🇸🇻', 'SV'), '504': ('Honduras', '🇭🇳', 'HN'), '505': ('Nicaragua', '🇳🇮', 'NI'), '506': ('Costa Rica', '🇨🇷', 'CR'),
    '507': ('Panama', '🇵🇦', 'PA'), '509': ('Haiti', '🇭🇹', 'HT'), '590': ('Guadeloupe', '🇬🇵', 'GP'), '591': ('Bolivia', '🇧🇴', 'BO'),
    '592': ('Guyana', '🇬🇾', 'GY'), '593': ('Ecuador', '🇪🇨', 'EC'), '595': ('Paraguay', '🇵🇾', 'PY'), '597': ('Suriname', '🇸🇷', 'SR'),
    '598': ('Uruguay', '🇺🇾', 'UY'), '673': ('Brunei', '🇧🇳', 'BN'), '675': ('Papua New Guinea', '🇵🇬', 'PG'), '676': ('Tonga', '🇹🇴', 'TO'),
    '677': ('Solomon Islands', '🇸🇧', 'SB'), '678': ('Vanuatu', '🇻🇺', 'VU'), '679': ('Fiji', '🇫🇯', 'FJ'), '685': ('Samoa', '🇼🇸', 'WS'),
    '689': ('French Polynesia', '🇵🇫', 'PF'), '852': ('Hong Kong', '🇭🇰', 'HK'), '853': ('Macau', '🇲🇴', 'MO'), '855': ('Cambodia', '🇰🇭', 'KH'),
    '856': ('Laos', '🇱🇦', 'LA'), '880': ('Bangladesh', '🇧🇩', 'BD'), '886': ('Taiwan', '🇹🇼', 'TW'), '960': ('Maldives', '🇲🇻', 'MV'),
    '961': ('Lebanon', '🇱🇧', 'LB'), '962': ('Jordan', '🇯🇴', 'JO'), '963': ('Syria', '🇸🇾', 'SY'), '964': ('Iraq', '🇮🇶', 'IQ'),
    '965': ('Kuwait', '🇰🇼', 'KW'), '966': ('Saudi Arabia', '🇸🇦', 'SA'), '967': ('Yemen', '🇾🇪', 'YE'), '968': ('Oman', '🇴🇲', 'OM'),
    '970': ('Palestine', '🇵🇸', 'PS'), '971': ('United Arab Emirates', '🇦🇪', 'AE'), '972': ('Israel', '🇮🇱', 'IL'),
    '973': ('Bahrain', '🇧🇭', 'BH'), '974': ('Qatar', '🇶🇦', 'QA'), '975': ('Bhutan', '🇧🇹', 'BT'), '976': ('Mongolia', '🇲🇳', 'MN'),
    '977': ('Nepal', '🇳🇵', 'NP'), '992': ('Tajikistan', '🇹🇯', 'TJ'), '993': ('Turkmenistan', '🇹🇲', 'TM'), '994': ('Azerbaijan', '🇦🇿', 'AZ'),
    '995': ('Georgia', '🇬🇪', 'GE'), '996': ('Kyrgyzstan', '🇰🇬', 'KG'), '77': ('Kazakhstan', '🇰🇿', 'KZ'), '998': ('Uzbekistan', '🇺🇿', 'UZ'), '383': ('Kosovo', '🇽🇰', 'XK'), '1242': ('Bahamas', '🇧🇸', 'BS'), '1246': ('Barbados', '🇧🇧', 'BB'),'1264': ('Anguilla', '🇦🇮', 'AI'), '1268': ('Antigua and Barbuda', '🇦🇬', 'AG'), '1284': ('British Virgin Islands', '🇻🇬', 'VG'), '1340': ('US Virgin Islands', '🇻🇮', 'VI'), '1345': ('Cayman Islands', '🇰🇾', 'KY'), '1441': ('Bermuda', '🇧🇲', 'BM'), '1473': ('Grenada', '🇬🇩', 'GD'), '1649': ('Turks and Caicos Islands', '🇹🇨', 'TC'), '1664': ('Montserrat', '🇲🇸', 'MS'), '1670': ('Northern Mariana Islands', '🇲🇵', 'MP'), '1671': ('Guam', '🇬🇺', 'GU'), '1684': ('American Samoa', '🇦🇸', 'AS'), '1721': ('Sint Maarten', '🇸🇽', 'SX'), '1758': ('Saint Lucia', '🇱🇨', 'LC'), '1767': ('Dominica', '🇩🇲', 'DM'), '1784': ('Saint Vincent and the Grenadines', '🇻🇨', 'VC'), '1809': ('Dominican Republic', '🇩🇴', 'DO'), '1829': ('Dominican Republic', '🇩🇴', 'DO'), '1849': ('Dominican Republic', '🇩🇴', 'DO'), '1868': ('Trinidad and Tobago', '🇹🇹', 'TT'), '1869': ('Saint Kitts and Nevis', '🇰🇳', 'KN'), '1876': ('Jamaica', '🇯🇲', 'JM'),
}

# Database Class
class Database:
    _instance = None
    _connection = None
    _lock = threading.RLock() 
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._connection = sqlite3.connect('numbers.db', check_same_thread=False, timeout=60)
            cls._connection.row_factory = sqlite3.Row
            cls._connection.execute("PRAGMA journal_mode=WAL;")
            cls._connection.execute("PRAGMA synchronous=NORMAL;")
            cls._connection.execute("PRAGMA cache_size=-64000;") 
            cls.init_db()
        return cls._instance

    @classmethod
    def init_db(cls):
        with cls._lock:
            c = cls._connection.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users
                         (user_id INTEGER PRIMARY KEY, 
                          username TEXT, 
                          first_name TEXT, 
                          last_name TEXT, 
                          join_date TEXT, 
                          is_banned INTEGER DEFAULT 0,
                          balance REAL DEFAULT 0.0, 
                          total_earned REAL DEFAULT 0.0)''')
            c.execute('''CREATE TABLE IF NOT EXISTS numbers
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, country TEXT, number TEXT UNIQUE, service TEXT, 
                         is_used INTEGER DEFAULT 0, used_by INTEGER, use_date TEXT)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS countries
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, code TEXT)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS user_stats
             (id INTEGER PRIMARY KEY AUTOINCREMENT, 
              user_id INTEGER, 
              date TEXT, 
              numbers_today INTEGER DEFAULT 0, 
              UNIQUE(user_id, date))''')


            c.execute('''CREATE TABLE IF NOT EXISTS cooldowns
                         (user_id INTEGER PRIMARY KEY, timestamp INTEGER)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS notifications
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, country TEXT, notified INTEGER DEFAULT 0)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS sms_history
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT, message TEXT, receive_date TEXT)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS public_sms_history
                         (hash TEXT PRIMARY KEY, date_added TEXT)''')

            c.execute('''CREATE TABLE IF NOT EXISTS bot_status
                         (id INTEGER PRIMARY KEY CHECK (id = 1), is_enabled INTEGER DEFAULT 1)''')
            
            c.execute("INSERT OR IGNORE INTO bot_status (id, is_enabled) VALUES (1, 1)")

            c.execute('''CREATE TABLE IF NOT EXISTS channel_settings
                         (id INTEGER PRIMARY KEY CHECK (id = 1),
                          main_channel TEXT,
                          backup_channel TEXT,
                          backup_channel_link TEXT,
                          otp_channel TEXT)''')

            c.execute("""INSERT OR IGNORE INTO channel_settings 
                         (id, main_channel, backup_channel, backup_channel_link, otp_channel)
                         VALUES (1, ?, ?, ?, ?)""",
                      (DEFAULT_MAIN_CHANNEL,
                       DEFAULT_BACKUP_CHANNEL,
                       DEFAULT_BACKUP_CHANNEL_LINK,
                       DEFAULT_OTP_CHANNEL))
            
            c.execute('''CREATE TABLE IF NOT EXISTS otp_stats (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             user_id INTEGER,
             country TEXT,
             service TEXT,
             timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')

            
            c.execute('''CREATE TABLE IF NOT EXISTS settings 
                         (id INTEGER PRIMARY KEY, otp_reward REAL, ref_reward REAL)''')
            
            c.execute('''INSERT OR IGNORE INTO settings (id, otp_reward, ref_reward) 
                         VALUES (1, 0.004, 0.0100)''')

            c.execute('''CREATE TABLE IF NOT EXISTS multi_chats
                         (chat_id TEXT PRIMARY KEY, chat_name TEXT)''')

            c.execute("PRAGMA table_info(users)")
            columns = [column[1] for column in c.fetchall()]
            
            if 'balance' not in columns:
                c.execute("ALTER TABLE users ADD COLUMN balance REAL DEFAULT 0.0")
                logger.info("✅  The 'balance' column was successfully added automatically..")
                
            if 'total_earned' not in columns:
                c.execute("ALTER TABLE users ADD COLUMN total_earned REAL DEFAULT 0.0")
                logger.info("✅ The 'total_earned' column was successfully added automatically..")

            c.execute('''CREATE TABLE IF NOT EXISTS numbers
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, country TEXT, number TEXT UNIQUE, service TEXT, 
                         is_used INTEGER DEFAULT 0, used_by INTEGER, use_date TEXT)''')
            cls._connection.commit()

    @classmethod
    def migrate_db(cls):
        """Ensures balance column exists without deleting existing data."""
        with cls._lock:
            try:
                cls._connection.execute("ALTER TABLE users ADD COLUMN balance REAL DEFAULT 0.0")
                cls._connection.commit()
            except sqlite3.OperationalError:
                pass

    @classmethod
    def execute(cls, query, params=()):
        with cls._lock:
            try:
                c = cls._connection.cursor()
                c.execute(query, params)
                cls._connection.commit()
                return c
            except sqlite3.Error as e:
                logger.error(f"Database error: {e}")
                return cls._connection.cursor()

    @classmethod
    def commit(cls):
        """Fix: Added commit method so that 'db.commit()' outside the class does not error."""
        with cls._lock:
            cls._connection.commit()

db = Database()


def setup_statistics_db():
    db.execute('''CREATE TABLE IF NOT EXISTS otp_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        country TEXT,
        service TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        
    )''')

async def get_stock_count(country, service):
    with db._lock:
        c = db.execute(
            "SELECT COUNT(*) FROM numbers WHERE country = ? AND service = ? AND is_used = 0",
            (country, service)
        )
        return c.fetchone()[0]
        
def get_country_info(phone_number):
    sorted_prefixes = sorted(COUNTRY_CODES.keys(), key=lambda x: len(x), reverse=True)
    for prefix in sorted_prefixes:
        if phone_number.startswith(prefix.lstrip('+')):
            return COUNTRY_CODES[prefix][0]
    return "Unknown"

# === Helper Functions ===
def clean_number(phone):
    """Removes all non-digit characters for consistent formatting.."""
    return re.sub(r'\D', '', str(phone))
def cool_otp_get(message):
    if not message:
        return "N/A"
    msg = str(message)
    msg = re.sub(r'https?://\S+', '', msg)
    keywords = ['code', 'otp', 'pin', 'kode', 'password', 'verification', 'auth', 'login', 'clave', 'parola']
    kw_pattern = '|'.join(keywords)
    m = re.search(rf'(?:{kw_pattern})[^\d]{{0,20}}?(\d{{3}}[- ]?\d{{3}}|\d{{4,8}})', msg, re.I)
    if m:
        return re.sub(r'[ -]', '', m.group(1))
    m = re.search(rf'(\d{{3}}[- ]?\d{{3}}|\d{{4,8}})[^\d]{{0,20}}?(?:{kw_pattern})', msg, re.I)
    if m:
        return re.sub(r'[ -]', '', m.group(1))
    patterns = [r'\d{4,8}', r'\d{3}[- ]\d{3}', r'\d{2}[- ]\d{2}[- ]\d{2}', r'\d{4}[- ]\d{4}']
    for pat in patterns:
        for m in re.finditer(pat, msg):
            cand = m.group(0)
            digits = re.sub(r'[ -]', '', cand)
            if 4 <= len(digits) <= 8 and not re.match(r'\d{1,2}:\d{2}', cand):
                return digits
    return "N/A"

def load_accounts():
    """Load accounts from JSON file or create it with defaults if it doesn't exist."""
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading accounts JSON: {e}")
            return DEFAULT_ACCOUNTS
    else:
        with open(ACCOUNTS_FILE, "w") as f:
            json.dump(DEFAULT_ACCOUNTS, f, indent=4)
        return DEFAULT_ACCOUNTS

    # 4. Tidak ada OTP terdeteksi
    return "N/A"
ACCOUNTS = load_accounts()
def detect_sms_language(text):
    if not text or len(text) < 3:
        return "Too Short 📍"
        
    try:

        res = detect_langs(text)[0]
        lang_code = res.lang
        confidence = res.prob * 100

        lang_map = {
            'af': 'Afrikaans', 'ar': 'Arabic', 'bg': 'Bulgarian ', 
            'bn': 'Bengali', 'ca': 'Catalan', 'cs': 'Czech', 
            'cy': 'Welsh', 'da': 'Danish', 'de': 'German', 
            'el': 'Greek', 'en': 'English', 'es': 'Spanish', 
            'et': 'Estonian', 'fa': 'Persian', 'fi': 'Finnish', 
            'fr': 'French', 'gu': 'Gujarati', 'he': 'Hebrew', 
            'hi': 'Hindi', 'hr': 'Croatian', 'hu': 'Hungarian', 
            'id': 'Indonesian', 'it': 'Italian', 'ja': 'Japanese', 
            'kn': 'Kannada', 'ko': 'Korean', 'lt': 'Lithuanian', 
            'lv': 'Latvian', 'mk': 'Macedonian', 'ml': 'Malayalam', 
            'mr': 'Marathi', 'ne': 'Nepali', 'nl': 'Dutch', 
            'no': 'Norwegian', 'pa': 'Punjabi', 'pl': 'Polish', 
            'pt': 'Portuguese', 'ro': 'Romanian', 'ru': 'Russian', 
            'sk': 'Slovak', 'sl': 'Slovenian', 'so': 'Somali', 
            'sq': 'Albanian', 'sv': 'Swedish', 'sw': 'Swahili', 
            'ta': 'Tamil', 'te': 'Telugu', 'th': 'Thai', 
            'tl': 'Tagalog', 'tr': 'Turkish', 'uk': 'Ukrainian', 
            'ur': 'Urdu', 'vi': 'Vietnamese', 'zh-cn': 'Chinese', 
            'zh-tw': 'Chinese'
        }
        
        lang_name = lang_map.get(lang_code, f"Unknown ({lang_code.upper()})🎣")

        return f"{lang_name}"
        
    except Exception:
        return "Detection Failed ❌¸"

def get_country_from_number(number: str):
    for code in sorted(COUNTRY_CODES.keys(), key=lambda x: -len(x)):
        if number.startswith(code):
            data = COUNTRY_CODES[code]
            if isinstance(data, (list, tuple)):
                return {'name': data[0], 'flag': data[1] if len(data) > 1 else '🌐', 'iso': data[2] if len(data) > 2 else 'UN'}
            return data
    return {'name': 'Unknown', 'flag': '🌎', 'iso': 'UN'}

def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def save_already_sent(username, already_sent):
    with open(f"already_sent_{username}.json", "w") as f:
        json.dump(list(already_sent), f)

def load_already_sent(username):
    filename = f"already_sent_{username}.json"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return set(json.load(f))
    return set()

def load_processed_ids():
    if not os.path.exists(STATE_FILE): 
        return set()
    try:
        with open(STATE_FILE, 'r') as f: 
            return set(json.load(f))
    except (json.JSONDecodeError, FileNotFoundError): 
        return set()

def save_processed_id(sms_id):
    processed_ids = load_processed_ids()
    processed_ids.add(sms_id)
    with open(STATE_FILE, 'w') as f: 
        json.dump(list(processed_ids), f)
async def login(session, account):
    username, password = account['username'], account['password']
    base = account['base_url'].rstrip('/')
    login_url = f"{base}{account.get('login_path', '/login')}"
    signin_url = f"{base}{account.get('signin_path', '/signin')}"

    try:
        resp = await session.get(login_url, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"[{username}] Login page returned {resp.status_code}")
            return False

        soup = BeautifulSoup(resp.text, 'html.parser')

        if not soup.find('input', {'type': 'password'}):
            logger.warning(f"[{username}] No password field found – not a login page?")
            return False

        form = soup.find('form', {'method': 'post'}) or soup.find('form')
        if form:
            inputs = form.find_all('input')
        else:
            logger.warning(f"[{username}] No form found, using all inputs from page")
            inputs = soup.find_all('input')

        payload = {}
        captcha_answer = None

        try:
            match = re.search(r'(\d+)\s*([\+\*x])\s*(\d+)\s*=\s*\?', resp.text, re.IGNORECASE)
            if match:
                n1, op, n2 = int(match.group(1)), match.group(2).lower(), int(match.group(3))
                if '+' in op:
                    captcha_answer = str(n1 + n2)
                elif '*' in op or 'x' in op:
                    captcha_answer = str(n1 * n2)
                else:
                    captcha_answer = str(n1 + n2)
        except Exception as e:
            logger.error(f"[{username}] Captcha parsing error: {e}")

        for inp in inputs:
            name = inp.get('name')
            if not name:
                continue
            value = inp.get('value', '')
            inp_lower = name.lower()
            if 'user' in inp_lower or 'email' in inp_lower:
                payload[name] = username
            elif 'pass' in inp_lower:
                payload[name] = password
            elif 'capt' in inp_lower or 'ans' in inp_lower or 'code' in inp_lower:
                payload[name] = captcha_answer if captcha_answer else value
            else:
                payload[name] = value

        if not payload:
            logger.warning(f"[{username}] No input fields with names found – cannot log in")
            return False

        logger.info(f"[{username}] Attempting login with payload keys: {list(payload.keys())}")
        post_resp = await session.post(signin_url, data=payload, timeout=15)

        if any(x in post_resp.text.lower() for x in ['dashboard', 'logout', 'success', 'member']):
            logger.info(f"[{username}] Login Successful!!")
            await asyncio.sleep(1)
            return True

        logger.warning(f"[{username}] Login Failed. Response preview: {post_resp.text[:200]}")
        return False

    except Exception as e:
        logger.error(f"[{username}] Login Error: {e}")
        return False

# Ivassms
async def ivas_fetch_sms(client: httpx.AsyncClient, headers: dict, csrf_token: str):
    all_messages = []
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        start_date = yesterday
        end_date = today
        logger.info(f"IVAS Work: Fetching SMS from {start_date} to {end_date}")

        payload_range = {'from': start_date, 'to': end_date, '_token': csrf_token}
        resp_range = await client.post(IVAS_API_ENDPOINT, data=payload_range, headers=headers)
        if resp_range.status_code != 200:
            logger.error(f"IVAS range error: {resp_range.status_code}")
            return []

        soup_range = BeautifulSoup(resp_range.text, 'html.parser')
        ranges = []
        for div in soup_range.find_all('div', onclick=True):
            onclick = div.get('onclick')
            if 'toggleRange' in onclick:
                try:
                    rng = onclick.split("'")[1]
                    ranges.append(rng)
                except:
                    pass
        ranges = list(set(ranges))
        logger.info(f"IVAS Work: Found {len(ranges)} ranges")

        numbers_url = urljoin(IVAS_BASE_URL, "portal/sms/received/getsms/number")
        sms_url = urljoin(IVAS_BASE_URL, "portal/sms/received/getsms/number/sms")

        semaphore = asyncio.Semaphore(3)

        async def fetch_numbers_for_range(rng):
            async with semaphore:
                payload_numbers = {
                    'start': start_date,
                    'end': end_date,
                    'range': rng,
                    '_token': csrf_token
                }
                resp_numbers = await client.post(numbers_url, data=payload_numbers, headers=headers)
                if resp_numbers.status_code != 200:
                    logger.error(f"IVAS numbers error for {rng}: {resp_numbers.status_code}")
                    return []
                soup_numbers = BeautifulSoup(resp_numbers.text, 'html.parser')
                numbers = []
                for div in soup_numbers.find_all('div', onclick=True):
                    onclick = div.get('onclick')
                    try:
                        num = onclick.split("'")[1]
                        if num and num != rng:
                            numbers.append(num)
                    except:
                        pass
                return list(set(numbers))

        numbers_per_range = await asyncio.gather(*[fetch_numbers_for_range(rng) for rng in ranges])
        all_numbers = []
        for rng, numbers in zip(ranges, numbers_per_range):
            all_numbers.extend([(rng, num) for num in numbers])

        async def fetch_sms_for_number(rng, num):
            async with semaphore:
                payload_sms = {
                    'start': start_date,
                    'end': end_date,
                    'Number': num,
                    'Range': rng,
                    '_token': csrf_token
                }
                resp_sms = await client.post(sms_url, data=payload_sms, headers=headers)
                if resp_sms.status_code != 200:
                    logger.error(f"IVAS sms error for {num}: {resp_sms.status_code}")
                    return []
                soup_sms = BeautifulSoup(resp_sms.text, 'html.parser')
                sms_texts = [p.get_text(strip=True) for p in soup_sms.find_all('p')]
                if not sms_texts:
                    raw_text = soup_sms.get_text(separator='\n', strip=True)
                    if raw_text:
                        sms_texts = raw_text.split('\n')
                messages = []
                for sms in sms_texts:
                    if not sms:
                        continue
                    if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', sms.strip()):
                        logger.debug(f"Ignoring time-only message: {sms}")
                        continue
                    if '$' in sms and len(sms) < 15:
                        continue
                    otp = cool_otp_get(sms)
                    if otp == "N/A":
                        continue
                    service = detect_service("", sms)
                    unique_id = hashlib.md5(f"{num}-{sms}".encode()).hexdigest()
                    time_str = datetime.now().strftime('%H:%M:%S')
                    messages.append({
                        "id": unique_id,
                        "number": num,
                        "full_sms": sms,
                        "code": otp,
                        "service": service,
                        "time": time_str,
                        "sender": service
                    })
                return messages

        sms_results = await asyncio.gather(*[fetch_sms_for_number(rng, num) for (rng, num) in all_numbers])
        for msgs in sms_results:
            all_messages.extend(msgs)

        return all_messages

    except Exception as e:
        logger.error(f"Error in ivas_fetch_sms: {e}", exc_info=True)
        return []
async def ivas_monitoring_task():
    global IVAS_SESSION_CLIENT
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    if IVAS_SESSION_CLIENT is None:
        IVAS_SESSION_CLIENT = httpx.AsyncClient(timeout=40.0, follow_redirects=True, headers=headers)

    while True:
        try:
            processed_ids = load_processed_ids()
            logger.info("IVAS: Fetching login page...")
            resp = await IVAS_SESSION_CLIENT.get(IVAS_LOGIN_URL)
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            token_input = soup.find('input', {'name': '_token'})
            if not token_input:
                logger.warning("IVAS: _token not found on login page")
                await asyncio.sleep(10)
                continue

            login_data = {
                'email': IVAS_EMAIL,
                'password': IVAS_PASSWORD,
                '_token': token_input['value']
            }

            logger.info("IVAS: Attempting login...")
            login_resp = await IVAS_SESSION_CLIENT.post(IVAS_LOGIN_URL, data=login_data)

            if "login" in str(login_resp.url).lower():
                logger.warning("IVAS: Login failed. Check credentials.")
                await asyncio.sleep(35)
                continue

            logger.info("IVAS: Login successful!")
            csrf_token = extract_csrf_token(login_resp.text)
            if not csrf_token:
                logger.info("IVAS: CSRF token not found in login response, fetching dashboard...")
                dash_resp = await IVAS_SESSION_CLIENT.get(IVAS_BASE_URL)
                csrf_token = extract_csrf_token(dash_resp.text)
                if not csrf_token:
                    logger.warning("IVAS: CSRF token not found even after dashboard fetch.")
                    await asyncio.sleep(10)
                    continue

            logger.info(f"IVAS: CSRF token obtained: {csrf_token[:10]}...")

            while True:
                messages = await ivas_fetch_sms(IVAS_SESSION_CLIENT, headers, csrf_token)
                if messages == "session_expired":
                    logger.warning("IVAS: Session expired. Re-logging in...")
                    break

                if not messages:
                    await asyncio.sleep(0.1)
                    continue

                for msg in reversed(messages):
                    sms_id = msg.get("id")
                    if sms_id in processed_ids:
                        continue
                    
                    number = str(msg.get('number', ''))
                    if not number or number == "0" or len(number) < 5:
                        continue

                    clean_num = clean_number(number)
                    current_time = datetime.now().strftime('%H:%M:%S')
                    masked = f"{number[:2]}★★★★{number[-4:]}"
                    full_sms = msg.get('full_sms', '')
                    otp_code = msg.get('code', 'N/A')
                    service = msg.get('service', 'Unknown')
                    if service == 'Unknown':
                        service = detect_service("", full_sms)

                    with db._lock:
                        order = db.execute(
                            "SELECT used_by, country, service FROM numbers WHERE number = ? AND is_used = 1",
                            ('+' + clean_num,)
                        ).fetchone()

                    if order:
                        user_id = order[0]
                        country_db = order[1]
                        service_db = order[2]
                        logger.info(f"[IVAS DETECT] Number {number} matched User ID: {user_id}")
                        
                        try:
                            with db._lock:
                                db.execute("UPDATE numbers SET is_used = 2 WHERE number = ?", ('+' + clean_num,))
                                db.execute("INSERT INTO otp_stats (user_id, country, service) VALUES (?, ?, ?)", 
                                            (user_id, country_db, service_db))
                                db.commit()

                            await send_private_otp(user_id, number, full_sms, otp_code)

                            c_info_pub = get_country_info(number)
                            if isinstance(c_info_pub, tuple):
                                c_name_pub, c_flag_pub, c_iso_pub = c_info_pub
                            else:
                                c_name_pub = c_info_pub.get('name', 'Unknown')
                                c_flag_pub = c_info_pub.get('flag', '🌐')
                                c_iso_pub = c_info_pub.get('iso', 'UN')
                            c_short_pub = get_short_service(service)
                            text_public, pub_markup = format_public_message(
                                number, service, full_sms, otp_code, current_time,
                                masked, c_name_pub, c_iso_pub, c_flag_pub, c_short_pub
                            )
                            await broadcast_otp(text_public, pub_markup)
                            logger.info(f"[IVAS TRAFFIC] Public Broadcast success (private detected): {number}")
                            
                        except Exception as send_err:
                            logger.error(f"[-] IVAS ERROR: Fail to send private otp to {user_id}: {send_err}")
                    else:
                        try:
                            c_info = get_country_info(number)
                            if isinstance(c_info, tuple):
                                c_name, c_flag, c_iso = c_info
                            else:
                                c_name = c_info.get('name', 'Unknown')
                                c_flag = c_info.get('flag', '🌐')
                                c_iso = c_info.get('iso', 'UN')

                            c_short = get_short_service(service)
                            text_public, pub_markup = format_public_message(
                                number, service, full_sms, otp_code, current_time, 
                                masked, c_name, c_iso, c_flag, c_short
                            )
                            
                            await broadcast_otp(text_public, pub_markup)
                            logger.info(f"[IVAS TRAFFIC] Public Broadcast success: {number}")
                        except Exception as e:
                            logger.error(f"[-] IVAS ERROR: Broadcast failed for {number}: {e}")

                    save_processed_id(sms_id)
                    processed_ids.add(sms_id)

                await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"Critical error in ivas_monitoring_task: {e}", exc_info=True)
            if "NoneType" in str(e) or "client" in str(e).lower():
                IVAS_SESSION_CLIENT = None

# panel accunt (worker account}
async def fetch_data(session, account, method='GET'):
    base = account['base_url'].rstrip('/')
    url = build_api_url(account)

    referer_url = f"{base}/client/SMSCDRStats"

    sesskey = getattr(session, 'sesskey', None)
    if not sesskey:
        try:

            html_resp = await session.get(referer_url, timeout=15)
            if html_resp.status_code == 200:
                match = re.search(r'sesskey=([a-zA-Z0-9=]+)', html_resp.text)
                if match:
                    sesskey = match.group(1)
                    session.sesskey = sesskey
                    logger.info(f"[{account['username']}] Successfully stole Sesskey: {sesskey}")
        except Exception:
            pass
            
    if sesskey:
        url += f"&sesskey={sesskey}"

    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": referer_url
    }
    
    csrf_token = getattr(session, 'csrf_token', None)
    if csrf_token:
        headers["X-CSRF-TOKEN"] = csrf_token

    try:
        if method == 'GET':
            response = await session.get(url, headers=headers, timeout=15)
        else:
            response = await session.post(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            try:
                data = response.json()
                if "aaData" in data:
                    return data
            except json.JSONDecodeError:
                if is_login_page(response.text):
                    logger.warning(f"[{account['username']}] Sesi ditolak server saat narik data.")
                    session.sesskey = None
                    return "session_expired"
                else:
                    return None
                    
        elif response.status_code in [401, 403, 502, 503, 504]:
            logger.warning(f"[{account['username']}] Koneksi diblokir server (HTTP {response.status_code}).")
            session.sesskey = None
            return "session_expired"
            
        elif response.status_code == 404:
            logger.error(f"[{account['username']}] URL not found (404): {url}")
            return None
            
        return None
        
    except Exception as e:
        logger.error(f"[{account['username']}] Fetch error: {e}")
        return None



def is_login_page(html):
    """Heuristic: look for login form or title containing login/signin"""
    soup = BeautifulSoup(html, 'html.parser')

    if soup.find('input', {'type': 'password'}):
        return True
    title = soup.find('title')
    if title and any(word in title.text.lower() for word in ['login', 'sign in', 'log in']):
        return True
    if 'login' in html.lower() or 'sign in' in html.lower():
        return True
    return False
def extract_csrf_token(html):
    """
    Extract CSRF token from HTML using multiple methods:
    1. <meta name="csrf-token" content="...">
    2. <input type="hidden" name="_token" value="...">
    3. JavaScript variables like window.csrfToken or var csrf_token
    """
    soup = BeautifulSoup(html, 'html.parser')
    meta = soup.find('meta', {'name': 'csrf-token'})
    if meta and meta.get('content'):
        return meta['content']
    hidden = soup.find('input', {'name': re.compile(r'_token|csrf', re.I)})
    if hidden and hidden.get('value'):
        return hidden['value']
    script_tags = soup.find_all('script')
    for script in script_tags:
        if script.string:
            match = re.search(r'window\.csrfToken\s*=\s*["\']([^"\']+)["\']', script.string)
            if match:
                return match.group(1)
            match = re.search(r'var\s+csrf_token\s*=\s*["\']([^"\']+)["\']', script.string)
            if match:
                return match.group(1)
    return None
async def worker(account):
    username = account['username']
    already_sent = load_already_sent(username)
    consecutive_failures = 0
    max_failures = 10
    backoff = 1

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': account['base_url'].rstrip('/') + account.get('login_path', '/login'),
    }

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as session:
        while True:
            try:
                if await login(session, account):
                    logging.info(f"[{username}] Login successful, fetching dashboard...")

                    base = account['base_url'].rstrip('/')
                    dashboard_candidates = ['/', '/dashboard', '/home', '/index']
                    csrf_token = None
                    for path in dashboard_candidates:
                        try:
                            dash_resp = await session.get(base + path, timeout=15)
                            if dash_resp.status_code == 200:
                                csrf_token = extract_csrf_token(dash_resp.text)
                                if csrf_token:
                                    logging.info(f"[{username}] CSRF token extracted from {path}")
                                    break
                        except Exception as e:
                            logging.debug(f"[{username}] Failed to fetch {path}: {e}")
                            continue
                    if not csrf_token:
                        logging.warning(f"[{username}] No CSRF token found in any candidate page")
                    session.csrf_token = csrf_token

                    logging.info(f"[{username}] Monitoring active...")
                    consecutive_failures = 0
                    backoff = 1
                    while True:
                        result = await sent_messages(session, account, already_sent)
                        if result == "relogin":
                            logging.info(f"[{username}] Session expired, relogging...")
                            break
                        elif result is None:
                            consecutive_failures += 1
                            if consecutive_failures > max_failures:
                                logging.warning(f"[{username}] Too many consecutive failures, backing off for {backoff} seconds...")
                                await asyncio.sleep(backoff)
                                backoff = min(backoff * 2, 300)
                                consecutive_failures = 0
                            else:
                                await asyncio.sleep(10)
                        else:
                            consecutive_failures = 0
                            backoff = 1
                            await asyncio.sleep(2)
                else:
                    logging.error(f"[{username}] Login failed, retrying in 60 seconds...")
                    await asyncio.sleep(60)
            except Exception as e:
                logging.error(f"Worker {username} Error: {e}")
                await asyncio.sleep(2)

async def sent_messages(session, account, already_sent):
    username = account['username']
    data = await fetch_data(session, account)
    
    if data == "session_expired": 
        return "relogin"
    
    if data is None:
        return None
    
    if data and isinstance(data, dict) and 'aaData' in data:
        for row in data['aaData']:

            if not isinstance(row, list) or len(row) < 5 or str(row[2]) == "0":
                continue

            try:
                date = str(row[0]).strip()
                number = str(row[2]).strip()
                sender = str(row[3]).strip()
                
                if len(row) >= 8:
                    message = str(row[7]).strip()
                else:

                    message = str(row[4]).strip()

                if not message or message == "0":
                    continue

                sms_hash = hashlib.md5(f"{date}{number}{message}".encode()).hexdigest()
                if sms_hash in already_sent:
                    continue

                match = re.search(r'\d{3}-\d{3}|\b\d{4,8}\b', message)
                otp = match.group() if match else "N/A"

                clean_rc = re.sub(r'\D', '', number)
                full_number = '+' + clean_rc
                
                if not clean_rc or clean_rc == "0":
                    continue


                with db._lock:
                    user_data = db.execute(
                        "SELECT used_by, country, service FROM numbers WHERE number = ? AND is_used = 1",
                        (full_number,)
                    ).fetchone()

                if user_data:
                    target_id = user_data[0]
                    country_name = user_data[1]
                    service_name = user_data[2]
                    
                    logger.info(f"[√] [DETECT] {username} found OTP for User: {target_id} | Num: {number}")

                    with db._lock:
                        db.execute("UPDATE numbers SET is_used = 2 WHERE number = ?", (full_number,))
                        db.execute(
                            "INSERT INTO otp_stats (user_id, country, service) VALUES (?, ?, ?)",
                            (target_id, country_name, service_name)
                        )
                        db.commit()

                    await send_private_otp(target_id, number, message, otp)

                    masked_pub = f"{clean_rc[:2]}★★★★{clean_rc[-4:]}"
                    c_info_pub = get_country_info(number)
                    if isinstance(c_info_pub, tuple):
                        c_name_pub, c_flag_pub, c_iso_pub = c_info_pub
                    else:
                        c_name_pub = c_info_pub.get('name', 'Unknown')
                        c_flag_pub = c_info_pub.get('flag', '🌐')
                        c_iso_pub = c_info_pub.get('iso', 'UN')

                    c_short_pub = get_short_service(sender)
                    text_pub, markup_pub = format_public_message(
                        number, sender, message, otp, date, masked_pub,
                        c_name_pub, c_iso_pub, c_flag_pub, c_short_pub
                    )
                    await broadcast_otp(text_pub, markup_pub)
                    logger.info(f"[TRAFFIC] Public Broadcast success (private detected): {number}")

                else:
                    logger.info(f"[•] [PUBLIC] Incoming SMS on {username}: {number}")
                    
                    masked = f"{clean_rc[:2]}★★★★{clean_rc[-4:]}"
                    c_info = get_country_info(number)
                    
                    if isinstance(c_info, tuple):
                        c_name, c_flag, c_iso = c_info
                    else:
                        c_name = c_info.get('name', 'Unknown')
                        c_flag = c_info.get('flag', '🌐')
                        c_iso = c_info.get('iso', 'UN')

                    c_short = get_short_service(sender)
                    text, markup = format_public_message(
                        number, sender, message, otp, date, masked,
                        c_name, c_iso, c_flag, c_short
                    )

                    await broadcast_otp(text, markup)

                already_sent.add(sms_hash)
                save_already_sent(username, already_sent)

            except Exception as row_err:
                logger.error(f"Error processing row: {row_err}")
                continue
       
        return True

    return False
def build_api_url(account, start_date=None, end_date=None):
    base = account['base_url'].rstrip('/')
    path = account.get('api_path', '/client/res/data_smscdr.php')
    
    if start_date is None:
        start_date = datetime.now().strftime('%Y-%m-%d 00:00:00')
    if end_date is None:
        end_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d 23:59:59')
    
    start_encoded = start_date.replace(' ', '%20')
    end_encoded = end_date.replace(' ', '%20')
    
    return (
        f"{base}{path}?fdate1={start_encoded}&fdate2={end_encoded}&"
        "frange=&fnum=&fcli=&fgdate=&fgmonth=&fgrange=&fgnumber=&fgcli=&fg=0&"
        "sEcho=1&iColumns=7&sColumns=%2C%2C%2C%2C%2C%2C&iDisplayStart=0&iDisplayLength=25&"
        "mDataProp_0=0&sSearch_0=&bRegex_0=false&bSearchable_0=true&bSortable_0=true&"
        "mDataProp_1=1&sSearch_1=&bRegex_1=false&bSearchable_1=true&bSortable_1=true&"
        "mDataProp_2=2&sSearch_2=&bRegex_2=false&bSearchable_2=true&bSortable_2=true&"
        "mDataProp_3=3&sSearch_3=&bRegex_3=false&bSearchable_3=true&bSortable_3=true&"
        "mDataProp_4=4&sSearch_4=&bRegex_4=false&bSearchable_4=true&bSortable_4=true&"
        "mDataProp_5=5&sSearch_5=&bRegex_5=false&bSearchable_5=true&bSortable_5=true&"
        "mDataProp_6=6&sSearch_6=&bRegex_6=false&bSearchable_6=true&bSortable_6=true&"
        "sSearch=&bRegex=false&iSortCol_0=0&sSortDir_0=desc&iSortingCols=1"
    )


async def fetch_api_data(url, params):
    async with httpx.AsyncClient(timeout=20, http2=True, follow_redirects=True) as client:
        try:
            response = await client.get(url, params=params)
            return response.json()
        except Exception as e:
            logger.error(f"API Error: {e}")
            return None          

def get_traffic_report(period='day'):
    if period == 'day':
        query_filter = "datetime('now', '-1 day')"
    elif period == 'week':
        query_filter = "datetime('now', '-7 days')"
    else:
        query_filter = "datetime('now', '-30 days')"

    rows = db.execute(f'''
        SELECT country, service, COUNT(*) as total 
        FROM otp_stats 
        WHERE timestamp >= {query_filter}
        GROUP BY country, service
        ORDER BY total DESC
    ''').fetchall()
    
    if not rows:
        return "No traffic recorded in this period."

    report = f"📊 *Traffic Report ({period.capitalize()})*\n"
    report += "----------------------------\n"
    for row in rows:
        report += f"📍 {row[0]} | {row[1].upper()}: `{row[2]}` OTP\n"
    
    return report
    
def record_traffic(user_id, country, service):
    """Universal function to log traffic to database"""
    with db._lock:
        db.execute(
            "INSERT INTO otp_stats (user_id, country, service) VALUES (?, ?, ?)", 
            (user_id, country, service)
        )
        db.commit()
        timestamp = datetime.now().strftime('%H:%M:%S')
        logger.info(f"[TRAFFIC] [{timestamp}] User:{user_id} | {country} | {service} | OTP Recorded!")
def get_channel_settings():
    try:
        with db._lock:
            res = db.execute("SELECT main_channel, backup_channel, backup_channel_link, otp_channel FROM channel_settings WHERE id = 1").fetchone()
            if res:

                return (res['main_channel'], res['backup_channel'], res['backup_channel_link'], res['otp_channel'])
            else:
                return (DEFAULT_MAIN_CHANNEL, DEFAULT_BACKUP_CHANNEL, DEFAULT_BACKUP_CHANNEL_LINK, DEFAULT_OTP_CHANNEL)
    except Exception as e:
        logger.error(f"Database error di get_channel_settings: {e}")
        return (DEFAULT_MAIN_CHANNEL, DEFAULT_BACKUP_CHANNEL, DEFAULT_BACKUP_CHANNEL_LINK, DEFAULT_OTP_CHANNEL)

def update_channel_settings(main=None, backup=None, link=None, otp=None):
    current_main, current_backup, current_link, current_otp = get_channel_settings()
    main = main if main not in (None, '') else current_main
    backup = backup if backup not in (None, '') else current_backup
    link = link if link not in (None, '') else current_link
    otp = otp if otp not in (None, '') else current_otp

    db.execute("""UPDATE channel_settings 
                  SET main_channel=?, backup_channel=?, backup_channel_link=?, otp_channel=?
                  WHERE id=1""",
               (main, backup, link, otp))

def is_bot_enabled():
    c = db.execute("SELECT is_enabled FROM bot_status WHERE id = 1")
    result = c.fetchone()
    return result[0] == 1 if result else True

# === SETTING PREMIUM EMOJI ===
def add_emoji_column():
    with db._lock:
        c = db.execute("PRAGMA table_info(settings)")
        columns = [column[1] for column in c.fetchall()]
        if 'use_premium_emoji' not in columns:
            db.execute("ALTER TABLE settings ADD COLUMN use_premium_emoji INTEGER DEFAULT 1")
            db.commit()
            logger.info("✅ Column 'use_premium_emoji' successfully added to settings table.")

def get_emoji_setting():
    add_emoji_column()
    with db._lock:
        res = db.execute("SELECT use_premium_emoji FROM settings WHERE id = 1").fetchone()
        return res[0] == 1 if res else True

def toggle_emoji_setting():
    current = get_emoji_setting()
    new_status = 0 if current else 1
    with db._lock:
        db.execute("UPDATE settings SET use_premium_emoji = ? WHERE id = 1", (new_status,))
        db.commit()
    return new_status == 1

def set_bot_status(enabled):
    status = 1 if enabled else 0
    db.execute("UPDATE bot_status SET is_enabled = ? WHERE id = 1", (status,))
    return True

def get_country_info(phone_number):
    clean_num = str(phone_number).replace('+', '').strip()
    for i in range(4, 0, -1):
        prefix = clean_num[:i]
        if prefix in COUNTRY_CODES:
            data = COUNTRY_CODES[prefix]
            if isinstance(data, (list, tuple)):
                return {
                    'name': data[0],
                    'flag': data[1] if len(data) > 1 else '🌐',
                    'iso': data[2] if len(data) > 2 else 'UN',
                    'short_cli': data[0][:3].upper()
                }
            return data
    return {'name': 'Unknown', 'flag': '🌎', 'iso': 'UN', 'short_cli': 'UNK'}


def get_short_service(sender_name):
    """Abbreviate the sender's name to 2-3 letters (eg: WhatsApp -> WS)"""
    if not sender_name: return "OT"
    name = sender_name.upper()
    if "WHATSAPP" in name: return "WS"
    if "FACEBOOK" in name: return "FB"
    if "GOOGLE" in name: return "GO"
    if "TELEGRAM" in name: return "TG"
    if "Instagram" in name: return "IG"
    if "TIKTOK" in name: return "TT"
    if "BITGET" in name: return "BG"
    if "APPLE" in name: return "AP"
    if "MICROSOFT" in name: return "MS"
    if "DISCORD" in name: return "DC"
    if "WECHAT" in name: return "WC"
    if "IMO" in name: return "IMO"
    if "SNAPCHAT" in name: return "SC"

    return name[:2]
def detect_service(sender_name, message_text):
    full_text = (str(sender_name) + " " + str(message_text)).lower()
    services = ['whatsapp', 'facebook', 'google', 'telegram', 'instagram', 'discord', 'twitter', 'snapchat', 'imo', 'tiktok']
    for service in services:
        if service in full_text: return service.capitalize()
    return sender_name if sender_name else "Unknown"

# --- BRIDGE FUNCTION
def send_async_message(chat_id, text, parse_mode=None, reply_markup=None, auto_delete=False):
    if GLOBAL_APP and MAIN_LOOP and not MAIN_LOOP.is_closed():
        async def sending():
            try:
                msg = await GLOBAL_APP.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                if auto_delete:
                    asyncio.create_task(auto_delete(chat_id, msg.message_id, 120))
            except Exception as error:
                logger.error(f"❌ Failed to send to {chat_id}: {error}", exc_info=True)
        asyncio.run_coroutine_threadsafe(sending(), MAIN_LOOP)
    else:
        logger.warning("⏳ Waiting for bot to be ready before sending message...")

# --- PUBLIC BROADCAST NOTIFICATION ---
def format_public_message(recipient_number, sender_name, message, otp, sms_time, masked_num, country_name, country_iso, country_flag, short_cli):
    number_otp = cool_otp_get(message)
    otp = number_otp if (number_otp and number_otp != "N/A") else "N/A"

    asset = SERVICE_ASSETS.get(short_cli, {"premium_id": None, "fallback": f"#{short_cli}"})

    display_service_basic = escape_html(asset["fallback"])

    if asset.get("premium_id"):
        display_service_premium = f'<tg-emoji emoji-id="{asset["premium_id"]}">📱</tg-emoji>'
    else:
        display_service_premium = display_service_basic

    try:
        detected_lang = detect(message).upper()
    except:
        detected_lang = "UN"

    safe_iso = re.sub(r'[^A-Z0-9]', '', str(country_iso).upper())
    safe_masked = escape_html(str(masked_num))
    safe_lang = re.sub(r'[^A-Z0-9]', '', str(detected_lang).upper())

    premium_flag = get_premium_flag(country_flag)
    text_premium = f"{premium_flag} #{safe_iso} {display_service_premium} {safe_masked} #{safe_lang}"
    text_basic = f"{country_flag} #{safe_iso} {display_service_basic} {safe_masked} #{safe_lang}"

    keyboard = [
        [
            InlineKeyboardButton(
                text=f"{BUTTON_ICONS['key']['fallback']} {otp}", 
                copy_text=CopyTextButton(text=otp),
                api_kwargs={
                    "style": "success", 
                    "icon_custom_emoji_id": BUTTON_ICONS['key']['premium_id']
                }
            ),
            InlineKeyboardButton(
                text=f"{BUTTON_ICONS['msg']['fallback']} Message",
                copy_text=CopyTextButton(text=message),
                api_kwargs={
                    "style": "danger", 
                    "icon_custom_emoji_id": BUTTON_ICONS['msg']['premium_id']
                }
            )
        ]
    ]
    
    return (text_premium, text_basic), InlineKeyboardMarkup(keyboard)
# --- PRIVATE NOTIFICATION ---
def format_private_message(recipient_number, message, otp, current_balance, reward_amount):
    otp = cool_otp_get(message) or "N/A"
    msg_body = str(message)

    text = (
         f"☎️ <b>Number :</b> <code>{recipient_number}</code>\n"
         f"🔑 <b>OTP :</b> <code>{otp}</code>\n"
         f"💸 <b>Reward:</b> {reward_amount:.4f}\n"
         f"💵 <b>Balance:</b> {current_balance:.4f}\n"
         f"⏰ <i>{datetime.now().strftime('%H:%M:%S')}</i>"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                text=f"{BUTTON_ICONS['key']['fallback']} Copy OTP: {otp}", 
                copy_text=CopyTextButton(text=otp),
                api_kwargs={
                    "style": "primary", 
                    "icon_custom_emoji_id": BUTTON_ICONS['key']['premium_id']
                }
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{BUTTON_ICONS['bell']['fallback']} Full Message", 
                copy_text=CopyTextButton(text=msg_body),
                api_kwargs={
                    "style": "success", 
                    "icon_custom_emoji_id": BUTTON_ICONS['bell']['premium_id']
                }
            )
        ]
    ]
    
    return text, InlineKeyboardMarkup(keyboard)

async def send_private_otp(user_id, number, message, otp):

    try:
        user = db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user:
            logger.warning(f"User {user_id} not in database, skipping private OTP.")
            return

        reward_amt = 0.005
        with db._lock:
            db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (reward_amt, user_id))
            db.commit()
            row = db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
            curr_bal = row[0] if row else 0.0

        final_text, reply_markup = format_private_message(number, message, otp, curr_bal, reward_amt)

        await application_bot.send_message(
            chat_id=user_id,
            text=final_text,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        logger.info(f"[SUCCESS] Private OTP sent to {user_id}")
    except Exception as e:
        logger.error(f"[-] ERROR: Fail to send private otp to {user_id}: {e}", exc_info=True)

async def broadcast_otp(text_data, markup, **kwargs):
    settings = get_channel_settings()
    primary_otp_chat = settings[3] if (len(settings) > 3 and settings[3]) else DEFAULT_OTP_CHANNEL

    target_chats = set()
    if primary_otp_chat:
        target_chats.add(primary_otp_chat)

    try:
        extra_chats = db.execute("SELECT chat_id FROM multi_chats").fetchall()
        for row in extra_chats:
            target_chats.add(row['chat_id'])
    except Exception as e:
        logger.error(f"Error fetching multi_chats: {e}")

    use_premium = get_emoji_setting()

    if isinstance(text_data, tuple):
        text_premium, text_basic = text_data
    else:
        text_premium = text_basic = text_data

    if not use_premium:
        text_premium = text_basic

    for cid in target_chats:
        if not cid:
            continue
        
        try:
            msg = await GLOBAL_APP.bot.send_message(
                chat_id=cid,
                text=text_premium,
                parse_mode=kwargs.get('parse_mode', ParseMode.HTML),
                reply_markup=markup,
                connect_timeout=30,
                read_timeout=30
            )
        except Exception as e:
            logger.warning(f"[!] Failed to send first message to {cid}, automatically switch to Short CLI...")
            try:
                msg = await GLOBAL_APP.bot.send_message(
                    chat_id=cid,
                    text=text_basic,
                    parse_mode=kwargs.get('parse_mode', ParseMode.HTML),
                    reply_markup=markup,
                    connect_timeout=30,
                    read_timeout=30
                )
            except Exception as fallback_err:
                logger.error(f"[!] Broadcast completely failed to {cid}: {fallback_err}")
                continue

        if kwargs.get('auto_delete', True):
            asyncio.create_task(auto_delete(cid, msg.message_id, 300))

def extract_numbers_from_content(content, filename):
    cleaned_numbers = []
    try:
        if filename.endswith('.xlsx'):
            import openpyxl
            wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
            sheet = wb.active
            for row in sheet.iter_rows(values_only=True):
                for cell in row:
                    if cell:
                        num = re.sub(r'\D', '', str(cell))
                        if 6 <= len(num) <= 30:
                            cleaned_numbers.append('+' + num)
        else:
            text_content = content.decode('utf-8', errors='ignore')
            matches = re.findall(r'\d{6,30}', text_content)
            for num in matches:
                cleaned_numbers.append('+' + num)
        return list(set(cleaned_numbers))
    except Exception as e:
        logger.error(f"Error extracting numbers: {e}")
        return []
        
def solve_math_captcha(soup):
    try:
        math_elements = soup.find_all(['label', 'span', 'p', 'div', 'b'])
        for element in math_elements:
            text = element.get_text()
            match = re.search(r'(\d+)\s*([\+\*xX])\s*(\d+)', text)
            if match:
                n1 = int(match.group(1))
                op = match.group(2).lower()
                n2 = int(match.group(3))
                
                res = n1 + n2 if op == '+' else n1 * n2
                logger.info(f" [CAPTCHA] Found: {n1} {op} {n2} = {res}")
                return str(res)

        captcha_input = soup.find('input', {'name': re.compile(r'capt|ans|res|code', re.I)})
        if captcha_input and captcha_input.get('placeholder'):
            p_text = captcha_input.get('placeholder')
            match = re.search(r'(\d+)\s*([\+\*xX])\s*(\d+)', p_text)
            if match:
                n1, op, n2 = int(match.group(1)), match.group(2).lower(), int(match.group(3))
                return str(n1 + n2 if op == '+' else n1 * n2)

    except Exception as e:
        logger.error(f"Error solve_captcha: {e}")
    return "0"

async def check_membership(user_id, context):
    try:
        main_ch, backup_ch, _, _ = get_channel_settings()

        # Normalize main_ch — strip URL prefix, ensure @ prefix
        if main_ch and main_ch.startswith('http'):
            main_ch = '@' + main_ch.rstrip('/').split('/')[-1]
        elif main_ch and not main_ch.startswith('-') and not main_ch.startswith('@'):
            main_ch = '@' + main_ch

        try:
            member1 = await context.bot.get_chat_member(chat_id=main_ch, user_id=user_id)
            if member1.status not in ['member', 'administrator', 'creator']:
                return False
        except Exception as e:
            logger.error(f"Error checking main channel ({main_ch}): {e}")

            return False

        if backup_ch and str(backup_ch).startswith('-100'):
            try:
                member2 = await context.bot.get_chat_member(chat_id=backup_ch, user_id=user_id)
                if member2.status not in ['member', 'administrator', 'creator']:
                    return False
            except Exception as e:
                logger.warning(f"Skipping backup check: {e}")
                pass 

        return True
    except Exception as e:
        logger.error(f"Global membership check error: {e}")
        return False

async def auto_delete(chat_id, message_id, delay=300):
    """Wait and delete message with error handling."""
    await asyncio.sleep(delay)
    try:

        await GLOBAL_APP.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"[*] [AUTO-DELETE] Success: {message_id} in {chat_id}")
    except Exception as e:
        logger.error(f"[!] [AUTO-DELETE] Failed: {e}")

        
async def traffic_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id 
    if user_id not in ADMIN_IDS:
        is_member = await check_membership(user_id, context)
        if not is_member:
            await update.message.reply_text("❌ Join channel first to see traffic.")
            return
    is_member = await check_membership(update.effective_user.id, context)
    if not is_member:
        await update.message.reply_text("❌ Join channel first to see traffic.")
        return
        
    report = get_traffic_report(period='day')
    await update.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id 
    username = user.username or "Unknown"
    if user.id in USER_STATE: del USER_STATE[user.id]
    user_exists = db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()

    args = context.args
    
    if not user_exists:
        referrer_id = None
        if args and args[0].isdigit():
            referrer_id = int(args[0])
            if referrer_id == user_id:
                referrer_id = None

        db.execute("""INSERT INTO users (user_id, username, first_name, join_date, balance) VALUES (?, ?, ?, ?, ?)""",(user_id, username, user.first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0.0))

        db.commit()

        if referrer_id:
            try:
                db.execute("UPDATE users SET balance = balance + 0.0050 WHERE user_id = ?", (referrer_id,))
                db.commit()
                
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"🎊 Someone joined using your link! You get a bonus balance of 0.0050$.."
                )
            except Exception as e:
                logger.error(f"Failed to give referral bonus: {e}")
                return

    c = db.execute("SELECT is_banned FROM users WHERE user_id = ?", (user.id,))
    res = c.fetchone()
    if res and res[0] == 1:
        await context.bot.send_message(chat_id, "❌ You are banned.")
        return

    is_member = await check_membership(user_id, context)
    
    if not is_member and user_id not in ADMIN_IDS:

        settings = get_channel_settings()
        main_ch = settings[0] if settings[0] else DEFAULT_MAIN_CHANNEL
        backup_link = settings[2] if (settings[2] and str(settings[2]).startswith('http')) else DEFAULT_BACKUP_CHANNEL_LINK
        otp_link = settings[3] if (settings[3] and str(settings[3]).startswith('http')) else OTP_LINK

        keyboard = [
    [InlineKeyboardButton("📢 Channel", url="https://t.me/channelbantuanmacha")],
    [InlineKeyboardButton("🔗 Grup Testimoni", url="https://t.me/testimoni_macha")],
    [InlineKeyboardButton("🔐 OTP Group", url=otp_link)],
    [InlineKeyboardButton("✅ Check Membership", callback_data="check_membership")]
]
        
        await context.bot.send_message(
            chat_id=chat_id, 
            text="❌ **Access Denied!**\n\nYou must join our channels to use this bot.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return


    await show_main_menu(update, context)
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [KeyboardButton("☎️ Get Number"), KeyboardButton("Clear Prefix")],
        [KeyboardButton("🏦 My Balance"), KeyboardButton("💸 Withdraw")],
        [KeyboardButton("❓ Help")]
    ]
    if user_id in ADMIN_IDS:
        keyboard.append(["Admin Panel"])

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False
    )
    text = "Hello there, select your menu below"
    await update.effective_message.reply_text(text, reply_markup=reply_markup)
async def handle_main_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "☎️ Get Number":
        await show_service_menu(update, context)

    elif text == "Clear Prefix":
        await update.message.reply_text("✅ Prefix cleared (dummy implementation).")

    elif text == "🏦 My Balance":
        await balance_command(update, context)

    elif text == "💸 Withdraw":
        with db._lock:
            res = db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        balance = res['balance'] if res else 0.0
        if balance < 1.0:
            await update.message.reply_text(
                f"❌ Withdraw Failed\n\nYour Balance: ${balance:.4f}\nMinimum Withdrawal: $1\n\nCollect more balance!",
                parse_mode=ParseMode.HTML
            )
        else:
            USER_STATE[user_id] = "WAITING_WD_ADDRESS"
            await update.message.reply_text("Please send your withdrawal address (Binance Pay ID or TRC20):")

    elif text == "❓ Help":
        help_text = (
            "❓ **Help**\n\n"
            "• **Get Number** – Pilih layanan dan negara untuk mendapatkan nomor.\n"
            "• **Clear Prefix** – Hapus prefix nomor (jika ada).\n"
            "• **My Balance** – Lihat saldo dan riwayat pendapatan.\n"
            "• **Withdraw** – Tarik saldo (min $1).\n"
            "• **Admin Panel** – Untuk administrator.\n\n"
            "Kontak @MACHA_KZ untuk bantuan lebih lanjut."
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    elif text == "Admin Panel" and user_id in ADMIN_IDS:
        await admin_panel(update, context)

    else:
        await update.message.reply_text("Select the options available on the keyboard.")
async def show_service_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SERVICES = {
        "whatsapp": {"name": "WhatsApp", "emoji_id": "5334998226636390258"},
        "telegram": {"name": "Telegram", "emoji_id": "5330237710655306682"},
        "facebook": {"name": "FaceBook", "emoji_id": "5323261730283863478"}
    }
    
    keyboard = []
    row = []
    
    for code, data in SERVICES.items():
        row.append(
            InlineKeyboardButton(
                text=data["name"], 
                callback_data=f"svc_{code}",
               icon_custom_emoji_id=data["emoji_id"],
                style="primary"
            )
        )
        if len(row) == 1:
            keyboard.append(row)
            row = []
            
    if row:
        keyboard.append(row)
        
    markup = InlineKeyboardMarkup(keyboard)
    text = "🌐 Please select the **Service** you wish to use:"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emoji_status = "✅ ON" if get_emoji_setting() else "❌ OFF"
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Numbers", callback_data="admin_add_numbers"), InlineKeyboardButton("🗑️ Remove Numbers", callback_data="admin_remove_numbers")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"), InlineKeyboardButton("👤 User Management", callback_data="admin_users")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"), InlineKeyboardButton("🔍 Find Number", callback_data="admin_find_number")],
        [InlineKeyboardButton("⚙️ Channel Settings", callback_data="admin_channel_settings"), InlineKeyboardButton("📦 Backup Code", callback_data="admin_backup")],
        [InlineKeyboardButton("➖ Reduce Balance", callback_data="admin_reduce_bal"), InlineKeyboardButton("🖥️ Add Panel Acc", callback_data="admin_add_panel")],
        [InlineKeyboardButton("⚡ Quick Add", callback_data="admin_quick_add"), InlineKeyboardButton("📥 Grab Numbers", callback_data="admin_grab_numbers")],
        [InlineKeyboardButton("📱 Manage Chat ID", callback_data="admin_manage_chats"), InlineKeyboardButton(f"🌟 Emoji Premium status: {emoji_status}", callback_data="admin_toggle_emoji")],
        [InlineKeyboardButton("🔄 Restart Bot", callback_data="admin_restart")]
    ]
    
    text = "🔧 **Admin Control Panel**\n\nSelect a management option below:"
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    await query.answer()

    if not is_bot_enabled() and user_id not in ADMIN_IDS:
        await query.answer("❌ Maintenance mode.", show_alert=True)
        return

    if data in ["main_menu", "back_to_main"]:
        if user_id in USER_STATE: del USER_STATE[user_id]
        await show_main_menu(update, context)
        return

    if data == "back_to_countries":
        await query.message.edit_text("Select Service Back:", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]))
        return


    # --- Membership Check ---
    if data == "check_membership":
        await query.answer("Checking membership status...") 
        
        is_joined = await check_membership(user_id, context)
        
        if is_joined:
            try:
                await query.message.delete()
            except:
                pass

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "<b>✅ Membership Verified!</b>\n\n"
                    "Thank you for joining. Now please type /start "
                    "back to access the bot's main menu."
                ),
                parse_mode="HTML"
            )
        else:
            await query.answer(
                "❌ You have not joined all channels! "
                "Please join first then click check again.", 
                show_alert=True
            )
        return

    if data == "main_menu":
        await show_main_menu(update, context)
        return
    # --- Service Selection ---
    if data.startswith("svc_"):
        svc_code = data.split("_")[1]
        c = db.execute("SELECT DISTINCT country FROM numbers WHERE is_used = 0 AND service = ?", (svc_code,))
        countries = c.fetchall()
        
        if not countries:
            await query.message.edit_text(f"❌ Stock for {svc_code.upper()} is empty!", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]]))
            return

        kb = []
        row = []
        for res in countries:
            c_name = res[0]
            stock = await get_stock_count(c_name, svc_code)
            kb.append([InlineKeyboardButton(f"🌎 {c_name} ({stock})", callback_data=f"get_{c_name}_{svc_code}")])
            if len(row) == 2:
                kb.append(row)
                row = []
        if row: kb.append(row)
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_main")])
        await query.message.edit_text(f"📂 Service: {svc_code.upper()}\nChoose Country:", reply_markup=InlineKeyboardMarkup(kb))

    if data.startswith("get_"):
        parts = data.split("_")
        country = parts[1]
        svc = parts[2]

        stock_now = await get_stock_count(country, svc)
        if stock_now < 5:
            await query.answer("❌ Stock empty! Need at least 5 numbers.", show_alert=True)
            return


        c = db.execute("SELECT number FROM numbers WHERE country = ? AND service = ? AND is_used = 0 LIMIT 5", (country, svc))
        res_list = c.fetchall()

        
        if len(res_list) < 5:
            await query.answer("❌ Stock less than 5 numbers!", show_alert=True)
            return

        nums = [r[0] for r in res_list]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for n in nums:
            db.execute("UPDATE numbers SET is_used = 1, used_by = ?, use_date = ? WHERE number = ?", (user_id, now, n))
        
        text = f"You has been assigned 5 number\n\n🌎 Country: {country}\n"
        for i, n in enumerate(nums, 1):
            text += f"{i}ï¸ `{n}`\n"
        
        all_nums = "\n".join(nums)
        kb = [
    [InlineKeyboardButton("📋 Copy All Numbers", copy_text=CopyTextButton(text=all_nums), style="primary")],
    [InlineKeyboardButton("🔄 Change Number", callback_data=f"get_{country}_{svc}")],
    [InlineKeyboardButton("🌎 Change Country", callback_data=f"svc_{svc}")]
]
        await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


    if data == "withdraw_request":
        res = db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        balance = res['balance'] if res else 0.0
        if balance < 1.0:

            await query.message.edit_text(
                f"❌ <b>Withdraw Failed</b>\n\n"
                f"Your Balance: <code>${balance:.4f}</code>\n"
                f"Minimum Withdrawal: <code>$1</code>\n\n"
                f"Collect more balance!",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]])
            )
            return
        keyboard = [
            [InlineKeyboardButton("Binance (Pay ID)", callback_data="wd_type_Binance")],
            [InlineKeyboardButton("TRX (TRC20)", callback_data="wd_type_TRX")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
        ]
        await query.message.edit_text(f"💰 Balance: ${balance:.4f}\n Select withdrawal method:", 
                                      reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("wd_type_"):
        method = data.split("_")[2]
        USER_STATE[user_id] = f"WAITING_WD_ADDRESS_{method}"
        await query.message.edit_text(f"📍 Please send your {method} Address/ID :")
        return


    # --- ADMIN ACTIONS ---
    if user_id not in ADMIN_IDS: return

    if data == "admin_panel":
        await admin_panel(update, context)
        return
        
    # --- MAIN MULTI-CHAT MENU ---
    if data == "admin_manage_chats":
        chats = db.execute("SELECT * FROM multi_chats").fetchall()
        msg = "📱 **Multi-Chat Management**\n\n"
        if not chats:
            msg += "_No extra chat IDs registered._"
        for c in chats:
            msg += f"• `{c['chat_id']}`\n  └ {c['chat_name']}\n\n"
        
        kb = [
            [InlineKeyboardButton("➕ Add Chat ID", callback_data="add_new_chat")],
            [InlineKeyboardButton("🗑️ Delete Chat ID", callback_data="list_delete_chat")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
        ]
        await query.message.edit_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))
    if data == "add_new_chat":
        USER_STATE[user_id] = "WAITING_CHAT_ID"
        await query.edit_message_text(
            "<b>➕ ADD NEW CHAT ID</b>\n\n"
            "Please send the Chat ID (usually starts with -100).\n"
            "Example: <code>-100123456789</code>\n\n",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="manage_chat_id")]])
        )
        return

    if data == "list_delete_chat":
        with db._lock:
            chats = db.execute("SELECT id, chat_name, chat_id FROM custom_chats").fetchall()
        
        if not chats:
            await query.answer("📭 No custom Chat IDs found.", show_alert=True)
            return

        buttons = []
        for c_id_db, c_name, c_val in chats:
            buttons.append([InlineKeyboardButton(f"🗑 {c_name} ({c_val})", callback_data=f"delchat_{c_id_db}")])
        
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="manage_chat_id")])
        await query.edit_message_text("<b>🗑 SELECT CHAT TO DELETE:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("delchat_"):
        target_id = data.split("_")[1]
        with db._lock:
            db.execute("DELETE FROM custom_chats WHERE id = ?", (target_id,))
            db.commit()
        await query.answer("✅ Chat ID deleted successfully!", show_alert=True)

        with db._lock:
            chats = db.execute("SELECT id, chat_name, chat_id FROM custom_chats").fetchall()
        
        if not chats:
            await query.edit_message_text("📭 All custom Chat IDs have been deleted.", 
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="manage_chat_id")]]))
            return

        buttons = [[InlineKeyboardButton(f"🗑 {n} ({v})", callback_data=f"delchat_{i}")] for i, n, v in chats]
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="manage_chat_id")])
        await query.edit_message_text("<b>🗑 SELECT CHAT TO DELETE:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        return

    # --- ACTION: EXECUTE DELETE ---
    if data.startswith("exec_del_"):
        cid = data.replace("exec_del_", "")
        db.execute("DELETE FROM multi_chats WHERE chat_id = ?", (cid,))
        await query.answer(f"Chat ID {cid} removed successfully.", show_alert=True)
        data = "admin_manage_chats" 

    if data == "admin_reduce_bal":
        USER_STATE[user_id] = "WAITING_REDUCE_BAL_ID"
        await query.message.reply_text(
            "➖ <b>REDUCE USER BALANCE</b>\n\n"
            "Please enter the <b>User ID</b> whose balance you wish to deduct:",
            parse_mode="HTML"
        )
        return
    if data == "admin_add_panel":
        USER_STATE[user_id] = "WAITING_NEW_PANEL_ACC"
        msg = (
            "🖥️ <b>ADD NEW PANEL ACCOUNT</b>\n\n"
            "Please send panel account details in the following format:\n"
            "<code>username|password|base_url</code>\n\n"
            "📌 <b>Example:</b>\n"
            "<code>admin123|passku123|http://123.45.67.89/ints</code>"
        )
        await query.message.reply_text(msg, parse_mode="HTML")
        return
    if data == "admin_quick_add":
        USER_STATE[user_id] = "WAITING_QUICK_SEARCH"
        msg = (
            "⚡ <b>QUICK ADD RANGE</b>\n\n"
            "Please provide the credentials and <b>Range Name</b>.\n"
            "The bot will fetch the exact Payterms and Max QTY dynamically.\n\n"
            "<code>Username | Password | Base_URL | Range Name</code>\n\n"
            "📌 <b>Example:</b>\n"
            "<code>admin | pass123 | http://123.45.67.89/ints | Bangladesh</code>"
        )
        await query.message.edit_text(msg, parse_mode="HTML")
        return

    if data.startswith("qpay_"):
        payterm_id = data.replace("qpay_", "")
        state_data = USER_STATE.get(user_id)
        
        if isinstance(state_data, dict) and state_data.get("state") == "WAITING_QUICK_PAYTERM":
            max_qty = state_data.get("max_qty", 50)
            range_name = state_data.get("range_name", "Unknown")
            
            USER_STATE[user_id]["payterm"] = payterm_id
            USER_STATE[user_id]["state"] = "WAITING_QUICK_QTY"
            
            await query.message.edit_text(
                f"🎯 <b>Range:</b> {escape_html(range_name)}\n"
                f"💳 <b>Selected Payterm ID:</b> <code>{payterm_id}</code>\n"
                f"📊 <b>Maximum Allowed QTY:</b> <code>{max_qty}</code>\n\n"
                f"✏️ <b>Enter the quantity to request:</b>\n"
                f"<i>(1 - {max_qty})</i>", 
                parse_mode="HTML"
            )
        return

    if data == "admin_grab_numbers":
        USER_STATE[user_id] = "WAITING_GRAB_NUMBERS"
        msg = (
            "📥 <b>GRAB MY NUMBERS</b>\n\n"
            "Please send the panel credentials.\n"
            "The bot will extract all your numbers and categorize them by Country/Range into <code>.txt</code> files.\n\n"
            "<code>Username | Password | Base_URL</code>\n\n"
            "📌 <b>Example:</b>\n"
            "<code>admin | pass123 | http://167.114.117.67/ints</code>"
        )
        await query.message.edit_text(msg, parse_mode="HTML")
        return
       
    if data == "admin_toggle_emoji":
        status = toggle_emoji_setting()
        await query.answer(f"Premium Emoji mode is now {'ON ✅' if status else 'OFF ❌'}", show_alert=True)
        await admin_panel(update, context)
        return
        
    if data == "admin_stats" or data.startswith("stat_"):
        # Default period
        period = "today"
        if data.startswith("stat_"):
            period = data.split("_")[1]

        # Time logic
        if period == "today":
            filter_sql = "datetime('now', 'start of day')"
            title = "Today"
        elif period == "7d":
            filter_sql = "datetime('now', '-7 days')"
            title = "Last 7 Days"
        elif period == "30d":
            filter_sql = "datetime('now', '-30 days')"
            title = "Last 30 Days"

        # Query Database
        total_otp = db.execute(f"SELECT COUNT(*) FROM otp_stats WHERE timestamp >= {filter_sql}").fetchone()[0]
        
        # Traffic by Country
        rows = db.execute(f"""
            SELECT country, COUNT(*) as qty 
            FROM otp_stats 
            WHERE timestamp >= {filter_sql} 
            GROUP BY country ORDER BY qty DESC LIMIT 5
        """).fetchall()

        msg = f"📊 **STATISTICS: {title}**\n"
        msg += f"━━━━━━━━━━━━━━━\n"
        msg += f"✅ **Total OTP:** `{total_otp}`\n\n"
        msg += f"🌍 **Top Countries:**\n"
        
        if rows:
            for r in rows:
                msg += f"• {r[0]}: `{r[1]}`\n"
        else:
            msg += "_No data recorded for this period._"

        kb = [
            [
                InlineKeyboardButton("Today", callback_data="stat_today"),
                InlineKeyboardButton("7 Days", callback_data="stat_7d"),
                InlineKeyboardButton("30 Days", callback_data="stat_30d")
            ],
            [InlineKeyboardButton("⬅️ Back to Admin", callback_data="admin_panel")]
        ]
        await query.message.edit_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


    if data == "admin_backup":
        await query.message.reply_text("⏳ Preparing Backup...")
        memory_file = io.BytesIO()
        

        target_files = ['bot.py', 'numbers.db', 'requirements.txt']
        exclude_dirs = {'.git', '__pycache__', '.cache', '.local', 'venv'}

        try:
            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk('.'):

                    dirs[:] = [d for d in dirs if d not in exclude_dirs]
                    
                    for file in files:

                        if file in target_files or file.endswith(('.py', '.db', '.txt')):
                            file_path = os.path.join(root, file)

                            arcname = os.path.relpath(file_path, '.')
                            zf.write(file_path, arcname=arcname)
            
            memory_file.seek(0)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            await query.message.reply_document(
                document=memory_file, 
                filename=f"Bot_Backup_{timestamp}.zip",
                caption="✅ Backup Complete!\nThis your backup."
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Backup failed: {e}")
        return

    if data == "admin_restart":
        await query.message.edit_text("🔄 The bot is restarting... Wait a moment.")

        try:
            db._connection.close()
        except:
            pass
        os.execv(sys.executable, [sys.executable] + sys.argv)
        

    if data == "admin_remove_numbers":
        kb = []
        c = db.execute("SELECT DISTINCT country FROM numbers")
        for cn in c.fetchall(): kb.append([InlineKeyboardButton(cn[0], callback_data=f"remove_{cn[0]}")])
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")])
        await query.message.edit_text("Select country to purge:", reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data.startswith("remove_"):
        cntry = data.split("_", 1)[1]
        db.execute("DELETE FROM numbers WHERE country = ?", (cntry,))
        await query.answer(f"Deleted numbers for {cntry}", show_alert=True)
        await admin_panel(update, context)
        return
    
    if data == "admin_add_numbers":
        USER_STATE[user_id] = "WAITING_ADD_SERVICE"
        await query.message.reply_text("📥 Add Numbers\nStep 1: Type the service name (e.g., ws, tg, google):")
        return
        
    if data == "admin_broadcast":
        USER_STATE[user_id] = "WAITING_BROADCAST_MSG"
        await query.message.reply_text("📢 Send broadcast message:")
        return

    if data == "admin_find_number":
        USER_STATE[user_id] = "WAITING_FIND_NUMBER"
        await query.message.reply_text("🔍 Send number (+123...):")
        return

    if data == "admin_channel_settings":
        kb = [[InlineKeyboardButton("Main", callback_data="set_main"), InlineKeyboardButton("OTP", callback_data="set_otp")]]
        main_ch, _, _, otp_ch = get_channel_settings()
        await query.message.edit_text(f"Settings:\nMain: {main_ch}\nOTP: {otp_ch}", reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data in ["set_main", "set_otp"]:
        USER_STATE[user_id] = data
        await query.message.reply_text(f"Send new ID/Link for {data}:")
        return
    if data.startswith("set_prefix_"):

        prefix_type = data.replace("set_prefix_", "")
        USER_STATE[user_id]['prefix'] = "+" if prefix_type == "plus" else ""
        await query.answer(f"Prefix set to: {USER_STATE[user_id]['prefix']}")
        return

    elif data == "confirm_import_pro":
        state_data = USER_STATE.get(user_id)
        if not state_data or 'pending_numbers' not in state_data:
            await query.answer("❌ Session expired. Please re-upload file.", show_alert=True)
            return

        await query.edit_message_text("⌛ Importing numbers to database... Please wait.")
        
        target_service = state_data.get('service', 'unknown')
        target_country = state_data.get('country_target', 'Unknown')
        numbers_list = state_data.get('pending_numbers', [])
        prefix = state_data.get('prefix', '')

        count, duplicates = 0, 0
        
        try:
            with db._lock:
                c = db._connection.cursor()
                for num_tuple in numbers_list:
                    phone = f"{prefix}{num_tuple[0]}"
                    try:
                        c.execute(
                            "INSERT INTO numbers (country, number, service, is_used) VALUES (?, ?, ?, 0)",
                            (target_country, phone, target_service)
                        )
                        count += 1
                    except sqlite3.IntegrityError:
                        duplicates += 1
                db._connection.commit()

            await query.message.reply_text(
                f"✅ {target_country} Has successfully added!\n\n"
                f"🛠 Service: {target_service.upper()}\n"
                f"🌍 Country: {target_country}\n"
                f"📥 Added: {count}\n"
                f"♻️ Duplicates: {duplicates}"
            )


            if count > 0:
                users = db.execute("SELECT user_id FROM users WHERE is_banned = 0").fetchall()
                notif_text = (
                    f"🚀 **RESTOCK ALERT!**\n\n"
                    f"Just added a new **{count} number** for country: **{target_country}** for {target_service.upper()} 🚀\n\n"
                    f"Come on, press /start now to get the latest stock numbers!"
                )

                async def broadcast_restock(u_list, text):
                    for u in u_list:
                        try:
                            await context.bot.send_message(u['user_id'], text, parse_mode=ParseMode.MARKDOWN)
                            await asyncio.sleep(0.05)
                        except: 
                            continue

                asyncio.create_task(broadcast_restock(users, notif_text))

        except Exception as e:
            logger.error(f"Import error: {e}")
            await query.message.reply_text(f"❌ Error processing file: {e}")

        if user_id in USER_STATE:
            del USER_STATE[user_id]
        

async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    state = USER_STATE.get(user_id)
    text = update.message.text

    if not state:
        return


    logger.info(f"DEBUG: Input dari {user_id} dengan state {state}: {text}")
    if state == "WAITING_CHAT_ID":

            try:
                chat_info = await context.bot.get_chat(text)
                title = chat_info.title or "Unknown"
                db.execute("INSERT OR REPLACE INTO multi_chats (chat_id, chat_name) VALUES (?, ?)", (text, title))
                await update.message.reply_text(f"✅ Successfully added: `{title}` [{text}]")
            except Exception as e:
                await update.message.reply_text(f"❌ Failed: Make sure the bot is already an admin in the chat. Error: {e}")
            del USER_STATE[user_id]
            return
    # --- PROSES WITHDRAW ---
    if isinstance(state, str) and state.startswith("WAITING_WD_ADDRESS_"):

        method = state.replace("WAITING_WD_ADDRESS_", "")
        res = db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        balance = res['balance'] if res else 0

        db.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))

        for admin in ADMIN_IDS:
            try:
                await context.bot.send_message(admin, 
                    f" ❗ <b>WD REQUEST!</b>\nUser: {user_id}\nMethod: {method}\nAddress: <code>{text}</code>\nAmount: ${balance:.4f}",
                    parse_mode=ParseMode.HTML)
            except: pass
            
        await update.message.reply_text("✅ WD request has been sent to admin. Your balance has been deducted..")
        del USER_STATE[user_id]
        return

    # --- ADMIN LOGIC ---
    if user_id in ADMIN_IDS:
        if state == "WAITING_ADD_SERVICE":
            USER_STATE[user_id] = f"WAITING_ADD_COUNTRY_{text.lower()}"
            await update.message.reply_text(f"🪪 Service set to: `{text.upper()}`\nStep 2: Type the Country name:")
            return
    if isinstance(state, str) and state.startswith("WAITING_ADD_COUNTRY_"):

        service_name = state.replace("WAITING_ADD_COUNTRY_", "")
        USER_STATE[user_id] = f"WAITING_FILE_{service_name}_{text}"
        await update.message.reply_text(f"🌎 Country: `{text}`\nStep 3: Please send the .txt/.xlsx file now.")
        return
    # --- ADMIN: REDUCE BALANCE LOGIC ---
    if user_id in ADMIN_IDS:
        if state == "WAITING_REDUCE_BAL_ID":
            target_id = text.strip()
            with db._lock:
                user_check = db.execute("SELECT first_name, balance FROM users WHERE user_id = ?", (target_id,)).fetchone()
            
            if user_check:
                USER_STATE[user_id] = {"state": "WAITING_REDUCE_BAL_AMT", "target_id": target_id}
                await update.message.reply_text(
                    f"👤 <b>User Found:</b> {user_check['first_name']}\n"
                    f"💰 <b>Current Balance:</b> ${user_check['balance']:.4f}\n\n"
                    f"Enter the <b>Nominal</b> balance you want to reduce (example: 0.5):",
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text("❌ User ID tidak ditemukan di database.")
                del USER_STATE[user_id]
            return

        if isinstance(state, dict) and state.get("state") == "WAITING_REDUCE_BAL_AMT":
            try:
                amount = float(text.strip())
                target_id = state["target_id"]
                
                with db._lock:
                    db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, target_id))
                    db.commit()
                    new_bal = db.execute("SELECT balance FROM users WHERE user_id = ?", (target_id,)).fetchone()[0]
                
                await update.message.reply_text(
                    f"✅ <b>Balance Successfully Reduced!</b>\n"
                    f"ID: <code>{target_id}</code>\n"
                    f"Cut: <code>-${amount:.4f}</code>\n"
                    f"The remaining balance: <code>${new_bal:.4f}</code>",
                    parse_mode="HTML"
                )
                
                try:
                    await context.bot.send_message(
                        chat_id=target_id,
                        text=f"⚠️ <b>Adjustment Balance</b>\nYour balance has been reduced by <b>${amount:.4f}</b> by Administrator.",
                        parse_mode="HTML"
                    )
                except: pass
                
            except ValueError:
                await update.message.reply_text("❌ Invalid nominal. Enter numbers only..")
            
            del USER_STATE[user_id]
            return
    if user_id in ADMIN_IDS:
        if state == "WAITING_NEW_PANEL_ACC":
            try:
                parts = text.split("|")
                if len(parts) != 3:
                    await update.message.reply_text("❌ Wrong format! Make sure you use the correct format.:\n`username|password|base_url`", parse_mode="Markdown")
                    return
                
                username_input = parts[0].strip()
                password_input = parts[1].strip()
                base_url_input = parts[2].strip().rstrip('/')
                
                new_acc = {
                    "username": username_input,
                    "password": password_input,
                    "base_url": base_url_input,
                    "login_path": "/login",
                    "signin_path": "/signin",
                    "api_path": "/client/res/data_smscdr.php"
                }
                
                current_accounts = load_accounts()
                if any(acc["username"] == username_input and acc["base_url"] == base_url_input for acc in current_accounts):
                    await update.message.reply_text("❌ The account with the Username and Base URL is already registered.!")
                    del USER_STATE[user_id]
                    return

                current_accounts.append(new_acc)
                with open(ACCOUNTS_FILE, "w") as f:
                    json.dump(current_accounts, f, indent=4)

                asyncio.create_task(worker(new_acc))
                
                await update.message.reply_text(
                    f"✅ <b>Panel Account Successfully Added!</b>\n\n"
                    f"👤 Username: <code>{username_input}</code>\n"
                    f"🌐 URL: {base_url_input}\n\n"
                    f"<i>The worker system for this panel has been automatically run in the background..</i>",
                    parse_mode="HTML"
                )
            except Exception as e:
                await update.message.reply_text(f"❌ An error occurred while saving: {e}")
                
            del USER_STATE[user_id]
            return
        if isinstance(state, str) and state == "WAITING_QUICK_SEARCH":
            try:
                parts = [p.strip() for p in text.split("|")]
                if len(parts) != 4:
                    await update.message.reply_text("❌ Invalid format.\nUse: `Username | Password | Base_URL | Range Name`", parse_mode="Markdown")
                    return
                
                username, password, base_url, range_name = parts
                base_url = base_url.rstrip('/')
                temp_acc = {"username": username, "password": password, "base_url": base_url, "login_path": "/login", "signin_path": "/signin"}

                status_msg = await update.message.reply_text(f"⏳ Searching for '{range_name}'...")
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/json, text/javascript, */*; q=0.01',
                    'X-Requested-With': 'XMLHttpRequest'
                }
                
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
                    if await login(client, temp_acc):
                        search_endpoints = [f"{base_url}/agent/res/data_smsranges.php", f"{base_url}/client/res/data_smsranges.php"]
                        params = {"sEcho": "1", "iDisplayStart": "0", "iDisplayLength": "100", "sSearch": range_name}
                        
                        success_data = None
                        for ep in search_endpoints:
                            resp = await client.get(ep, params=params)
                            if resp.status_code == 200:
                                try:
                                    success_data = resp.json()
                                    if "aaData" in success_data: break
                                except: pass
                        
                        if success_data and "aaData" in success_data:
                            found_rid = None
                            found_name = None
                            
                            for row in success_data["aaData"]:
                                row_name = BeautifulSoup(str(row[0]), "html.parser").get_text(strip=True)
                                html_btn = str(row[-1])
                                
                                if range_name.lower() in row_name.lower():
                                    match = re.search(r"info=['\"](\d+)['\"]", html_btn)
                                    if match:
                                        found_rid = match.group(1)
                                        found_name = row_name
                                        break
                            
                            if found_rid:
                                await status_msg.edit_text(f"⏳ Range found (RID: {found_rid}). Fetching configuration...")
                                
                                popup_endpoints = [f"{base_url}/agent/res/requestsmsnumber.php", f"{base_url}/agent/res/requestsmsnumber.php"]
                                popup_html = ""
                                for ep in popup_endpoints:
                                    resp = await client.post(ep, data={"rid": found_rid})
                                    if resp.status_code == 200 and "<select" in resp.text:
                                        popup_html = resp.text
                                        break
                                
                                if popup_html:
                                    soup = BeautifulSoup(popup_html, 'html.parser')
                                    
                                    kb = []
                                    payterm_select = soup.find('select', {'id': 'payterm'})
                                    if payterm_select:
                                        for opt in payterm_select.find_all('option'):
                                            val = opt.get('value')
                                            txt = opt.get_text(strip=True)
                                            if val:
                                                kb.append([InlineKeyboardButton(txt, callback_data=f"qpay_{val}")])
                                    
                                    max_qty = 50
                                    qty_select = soup.find('select', {'id': 'qty'})
                                    if qty_select:
                                        qtys = [int(opt.get('value')) for opt in qty_select.find_all('option') if opt.get('value') and opt.get('value').isdigit()]
                                        if qtys:
                                            max_qty = max(qtys)
                                            
                                    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")])
                                    
                                    USER_STATE[user_id] = {
                                        "state": "WAITING_QUICK_PAYTERM",
                                        "acc": temp_acc,
                                        "rid": found_rid,
                                        "range_name": found_name,
                                        "max_qty": max_qty
                                    }
                                    
                                    msg_text = (
                                        f"✅ <b>Target Configured!</b>\n"
                                        f"📍 <b>{escape_html(found_name)}</b>\n"
                                        f"🔑 <b>RID:</b> <code>{found_rid}</code>\n"
                                        f"📊 <b>Max QTY:</b> <code>{max_qty}</code>\n\n"
                                        f"👇 <b>Select Payterm:</b>"
                                    )
                                    await status_msg.edit_text(msg_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
                                else:
                                    await status_msg.edit_text("❌ Range found, but failed to fetch Payterm and QTY configuration.")
                            else:
                                await status_msg.edit_text(f"❌ '{range_name}' not found or no request button available.")
                        else:
                            await status_msg.edit_text("❌ Failed to fetch data from the server.")
                    else:
                        await status_msg.edit_text("❌ Login failed. Check credentials and Base URL.")
            except Exception as e:
                await update.message.reply_text(f"❌ Internal error: {e}")
            return

        if isinstance(state, dict) and state.get("state") == "WAITING_QUICK_QTY":
            qty = text.strip()
            if not qty.isdigit():
                await update.message.reply_text("❌ QTY must be a valid number.")
                return
            
            max_qty = state.get("max_qty", 50)
            if int(qty) > max_qty or int(qty) < 1:
                await update.message.reply_text(f"❌ Invalid amount. Limit is between 1 and {max_qty}.")
                return
            
            acc = state["acc"]
            rid = state["rid"]
            payterm = state["payterm"]
            base_url = acc["base_url"]
            
            status_msg = await update.message.reply_text("⏳ Processing request...")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*',
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
            }
            
            try:
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
                    if await login(client, acc):
                        exec_endpoints = [f"{base_url}/agent/res/requestsmsnumberfinal.php", f"{base_url}/client/res/requestsmsnumberfinal.php"]
                        payload = {"rid": rid, "payterm": payterm, "qty": qty}
                        
                        success = False
                        for ep in exec_endpoints:
                            resp = await client.post(ep, data=payload)
                            if resp.status_code == 200:
                                clean_resp = BeautifulSoup(resp.text, 'html.parser').get_text(strip=True) if resp.text else "Success"
                                await status_msg.edit_text(
                                    f"✅ <b>REQUEST EXECUTED</b>\n\n"
                                    f"<b>Range:</b> {escape_html(state['range_name'])}\n"
                                    f"<b>QTY:</b> {qty}\n\n"
                                    f"<b>Server Response:</b>\n"
                                    f"<code>{clean_resp}</code>", 
                                    parse_mode="HTML"
                                )
                                success = True
                                break
                                
                        if not success:
                            await status_msg.edit_text("❌ Execution failed. Endpoint not found or returned an error.")
                    else:
                        await status_msg.edit_text("❌ Login session expired.")
            except Exception as e:
                await status_msg.edit_text(f"❌ Error occurred: {e}")
                
            del USER_STATE[user_id]
            return
    # === FITUR GRAB NUMBERS ===
    if isinstance(state, str) and state == "WAITING_GRAB_NUMBERS":
        try:
            parts = text.split("|")
            if len(parts) != 3:
                await update.message.reply_text("❌ Wrong format! Use the correct format:\n`username|password|base_url`", parse_mode="Markdown")
                return

            username_input = parts[0].strip()
            password_input = parts[1].strip()
            base_url_input = parts[2].strip().rstrip('/')

            temp_acc = {
                "username": username_input,
                "password": password_input,
                "base_url": base_url_input,
                "login_path": "/login",
                "signin_path": "/signin"
            }

            status_msg = await update.message.reply_text(f"⏳ Start the Grab process from the panel {base_url_input}...")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': f"{base_url_input}/client/MySMSNumbers"
            }

            async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, headers=headers) as client:
                if await login(client, temp_acc):
                    await status_msg.edit_text("⏳ Login successful! Sucking all numbers from server...")

                    grab_url = f"{base_url_input}/client/res/data_smsnumbers.php?sEcho=1&iColumns=6&sColumns=%2C%2C%2C%2C%2C&iDisplayStart=0&iDisplayLength=-1"
                    
                    response = await client.get(grab_url)
                    
                    if response.status_code == 200:
                        try:
                            data = response.json()
                            aaData = data.get("aaData", [])
                            total_found = len(aaData)
                            
                            await status_msg.edit_text(f"⏳ Found {total_found} numbers. Processing and categorizing...")

                            valid_numbers = []
                            for row in aaData:
                                try:

                                    raw_number = str(row[2]).strip()
                                    

                                    clean_text = BeautifulSoup(raw_number, 'html.parser').get_text()
                                    clean_num = re.sub(r'\D', '', clean_text)
                                    

                                    if 8 <= len(clean_num) <= 15:
                                        valid_numbers.append("+" + clean_num)
                                except Exception:
                                    continue

                            if not valid_numbers:
                                await status_msg.edit_text("❌ Failed to extract number from server data. (Empty field or server format changed")
                                del USER_STATE[user_id]
                                return

                            count = 0
                            duplicates = 0
                            
                            with db._lock:
                                c = db._connection.cursor()
                                for num in valid_numbers:
                                    country_info = get_country_info(num)
                                    if isinstance(country_info, tuple):
                                        country_name = country_info[0]
                                    elif isinstance(country_info, dict):
                                        country_name = country_info.get('name', 'Unknown')
                                    else:
                                        country_name = "Unknown"

                                    service_name = "whatsapp"
                                    
                                    try:
                                        c.execute(
                                            "INSERT INTO numbers (country, number, service, is_used) VALUES (?, ?, ?, 0)",
                                            (country_name, num, service_name)
                                        )
                                        count += 1
                                    except sqlite3.IntegrityError:
                                        duplicates += 1
                                db._connection.commit()

                            await status_msg.edit_text(
                                f"✅ <b>GRAB NUMBERS DONE!</b>\n\n"
                                f"🌐 <b>Target:</b> <code>{base_url_input}</code>\n"
                                f"🎯 <b>Total:</b> {total_found} number\n"
                                f"📥 <b>Successfully Added:</b> {count} number\n"
                                f"♻️ <b>Failed (Duplicate):</b> {duplicates} number\n\n"
                                f"<i>All numbers have been automatically categorized according to their country..</i>",
                                parse_mode="HTML"
                            )

                        except json.JSONDecodeError:
                            await status_msg.edit_text(f"❌ Failed to process JSON data from server. Response: {response.text[:100]}...")
                    else:
                        await status_msg.edit_text(f"❌ Failed to retrieve data. The server responded with HTTP code {response.status_code}")
                else:
                    await status_msg.edit_text("❌ Login failed. Please double-check your username, password, or Captcha on the panel..")

        except Exception as e:
            logger.error(f"Error in Grab Number feature: {e}", exc_info=True)
            await update.message.reply_text(f"❌ A system error occurred: {e}")

        del USER_STATE[user_id]
        return



    if state == "WAITING_BROADCAST_MSG":
        c = db.execute("SELECT user_id FROM users WHERE is_banned = 0")
        users = c.fetchall()
        count = 0
        for u in users:
            try:
                await context.bot.send_message(u[0], text)
                count += 1
            except:
                pass
            await asyncio.sleep(0.05)
        await update.message.reply_text(f"✅ Sent to {count} users.")
        del USER_STATE[user_id]
        return

    if state == "WAITING_FIND_NUMBER":
        num = text.strip().replace(' ', '')
        if not num.startswith('+'):
            num = '+' + num
        res = db.execute("SELECT * FROM numbers WHERE number = ?", (num,)).fetchone()
        msg = f"Info: {dict(res)}" if res else "Not found."
        await update.message.reply_text(msg)
        del USER_STATE[user_id]
        return

    if state in ["set_main", "set_otp"]:
        if state == "set_main":
            update_channel_settings(main=text)
        elif state == "set_otp":
            update_channel_settings(otp=text)
        await update.message.reply_text("✅ Updated!")
        del USER_STATE[user_id]
        return
def clean_and_validate_numbers(raw_text):
    """Only take internationally sensible numbers (7-15 digits)"""

    potential_nums = re.findall(r'\d+', raw_text)
    
    validated = []
    for num in potential_nums:

        if 7 <= len(num) <= 15:
            if not num.startswith(('000', '111', '1234')):
                validated.append(num)
                
    return list(set(validated))
    
async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = USER_STATE.get(user_id)

    if user_id not in ADMIN_IDS or not isinstance(state, str) or not state.startswith("WAITING_FILE_"):
        return

    try:
        parts = state.split("_")
        service_name = parts[2]
        country_name = " ".join(parts[3:])

        doc = update.message.document
        file_ext = os.path.splitext(doc.file_name)[1].lower()

        if file_ext not in ['.txt', '.csv', '.xlsx']:
            await update.message.reply_text("❌ Format not supported! Use .txt, .csv, or .xlsx")
            return

        waiting = await update.message.reply_text("⏳ Downloading and analyzing numbers...")
        
        new_file = await doc.get_file()
        content = await new_file.download_as_bytearray()
        raw_text = ""

        if file_ext in ['.txt', '.csv']:
            raw_text = content.decode('utf-8', errors='ignore')
        elif file_ext == '.xlsx':
            import pandas as pd
            df = pd.read_excel(BytesIO(content))
            raw_text = " ".join(df.astype(str).values.flatten().tolist())

        found_nums = clean_and_validate_numbers(raw_text)
        
        if not found_nums:
            await waiting.edit_text("❌ No valid number found (minimum 7-15 digits).")
            return

        valid_data = []
        for num in found_nums:
            detected_country = "Unknown"

            for code in sorted(COUNTRY_CODES.keys(), key=lambda x: -len(x)):
                if num.startswith(code):
                    detected_country = COUNTRY_CODES[code][0]
                    break
            if detected_country != "Unknown":
                valid_data.append((num, detected_country))

        if not valid_data:
            await waiting.edit_text("❌ Number found but Prefix is not in the country list.")
            return

        USER_STATE[user_id] = {
            'pending_numbers': valid_data,
            'service': service_name,
            'country_target': country_name,
            'prefix': '' 
        }

        from collections import Counter
        countries_count = Counter([d[1] for d in valid_data])
        
        msg = (
            f"📊 **File Analysis Result**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🎯 Service: `{service_name.upper()}`\n"
            f"🌍 Target: `{country_name}`\n"
            f"🔢 Total Unique: `{len(valid_data)}` numbers\n\n"
            f"💡 **Detected by Prefix:**\n"
        )
        for c, q in countries_count.most_common(3):
            msg += f"• {c}: {q} qty\n"

        kb = [
            [InlineKeyboardButton("Add '+' Prefix", callback_data="set_prefix_plus"),
             InlineKeyboardButton("No Prefix", callback_data="set_prefix_none")],
            [InlineKeyboardButton("✅ START IMPORT", callback_data="confirm_import_pro")],
            [InlineKeyboardButton("❌ CANCEL", callback_data="admin_panel")]
        ]
        await waiting.edit_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

        # Restock notification is handled in confirm_import_pro callback

    except Exception as e:
        logger.error(f"Error in document_handler: {e}")
        await update.message.reply_text(f"❌ Error: {e}")
async def convert_to_txt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    raw_text = ""
    
    if message.reply_to_message:
        reply = message.reply_to_message
        if reply.document:
            try:
                msg_wait = await message.reply_text("⏳ *Downloading and extracting files...*", parse_mode='Markdown')
                file = await reply.document.get_file()
                file_bytes = await file.download_as_bytearray()
                mime_type = reply.document.mime_type
                filename = reply.document.file_name.lower()

                if filename.endswith('.pdf'):
                    import PyPDF2
                    pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
                    for page in pdf_reader.pages:
                        raw_text += page.extract_text() + "\n"
                elif filename.endswith('.docx'):
                    raw_text = file_bytes.decode('utf-8', errors='ignore')
                else:
                    raw_text = file_bytes.decode('utf-8', errors='ignore')
                
                await msg_wait.delete()
            except Exception as e:
                await message.reply_text(f"❌ Failed to process file: {e}")
                return

        elif reply.text:
            raw_text = reply.text

    elif context.args:
        raw_text = " ".join(context.args)

    if not raw_text:
        await message.reply_text(
            "🥀 *How to use:*\n"
            "1. Reply to file (TXT, CSV, PDF) with the `/convert command`.\n"
            "2. Reply to a text message containing a list of numbers with the command `/convert`.\n"
            "3. Type `/convert <list number>`.",
            parse_mode='Markdown'
        )
        return

    all_nums = clean_and_validate_numbers(raw_text)
    
    if not all_nums:
        await message.reply_text("❌ No valid number (7-15 digits) was found in the input..")
        return

    categorized_data = {}
    
    msg_proc = await message.reply_text(f"🔍 Found {len(all_nums)} numbers. Currently categorizing...")

    for num in all_nums:
        clean_num = re.sub(r'\D', '', num)
        c_info = get_country_info(clean_num)

        if isinstance(c_info, tuple):
            country_name = c_info[0]
            flag = c_info[1]
        elif isinstance(c_info, dict):
            country_name = c_info.get('name', 'Unknown')
            flag = c_info.get('flag', '🌐')
        else:
            country_name = c_info if c_info else "Unknown"
            flag = "🌐"

        category_key = f"{flag} {country_name}"
        
        if category_key not in categorized_data:
            categorized_data[category_key] = []
        categorized_data[category_key].append(num)

    for country_label, nums in categorized_data.items():
        unique_nums = sorted(list(set(nums)))
        count = len(unique_nums)
        final_content = "\n".join(unique_nums)

        file_io = io.BytesIO(final_content.encode('utf-8'))
        safe_filename = re.sub(r'[^\w\s-]', '', country_label).strip().replace(' ', '_')
        file_io.name = f"{safe_filename}_Number.txt"
        
        caption_text = (
            f"🌎 **Country:** `{country_label}`\n"
            f"🔢 **Amount:** `{count}` number\n\n"
            f"✅ *Successfully converted!*"
        )
        
        try:
            await context.bot.send_document(
                chat_id=message.chat_id,
                document=file_io,
                filename=file_io.name,
                caption=caption_text,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending file for {country_label}: {e}")

    await msg_proc.edit_text(f"✅ *Done!*\nSuccessfully processed {len(all_nums)} numbers into {len(categorized_data)} country categories.")

async def broadcast_restock(u_list, text, bot=None):
    for u in u_list:
        try:
            target_bot = bot or (GLOBAL_APP.bot if GLOBAL_APP else None)
            if target_bot:
                await target_bot.send_message(
                    chat_id=u['user_id'], 
                    text=text, 
                    parse_mode=ParseMode.HTML
                )
            await asyncio.sleep(0.05)
        except Exception:
            continue
            
async def command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd = update.message.text.split()[0]
    user_id = update.effective_user.id

    if cmd == '/backup' and user_id in ADMIN_IDS:
        await admin_panel(update, context)
    
    if cmd == '/push' and user_id in ADMIN_IDS:
        set_bot_status(False)
        await update.message.reply_text("✅ Maintenance ON.")
        
    if cmd == '/on' and user_id in ADMIN_IDS:
        set_bot_status(True)
        await update.message.reply_text("✅ Bot Online.")
        
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "User"

    with db._lock:
        res = db.execute(
            "SELECT balance, total_earned FROM users WHERE user_id = ?", 
            (user_id,)
        ).fetchone()

    if not res:

        curr_bal = 0.0
        total_earn = 0.0
    else:
        try:
            curr_bal = res['balance']
            total_earn = res['total_earned']
        except:
            curr_bal = res[0]
            total_earn = res[1]

    msg_text = (
        f"💳 **WALLET INFO**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 **User:** @{username}\n"
        f"🆔 **ID:** `{user_id}`\n\n"
        f"💰 **Current Balance:**\n"
        f"└─ `USD {curr_bal:.4f}`\n\n"
        f"📈 **Minimum Withdraw:**\n"
        f"└─ `1$`\n"
        f"━━━━━━━━━━━━━━━\n"
        f" _Keep active to earn more rewards!_"
    )

    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_balance")],
        [InlineKeyboardButton("📥 Withdraw", callback_data="withdraw_request")]
    ]

    await update.message.reply_text(
        msg_text, 
        parse_mode=ParseMode.MARKDOWN, 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def reff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={user_id}"
    await update.message.reply_text(f"🔗 <b>Your Referral Link:</b>\n<code>{link}</code>", parse_mode=ParseMode.HTML)


async def main():
    global GLOBAL_APP, MAIN_LOOP, application_bot
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    GLOBAL_APP = application
    MAIN_LOOP = asyncio.get_running_loop()
    application_bot = application.bot

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("traffic", traffic_user_command))
    application.add_handler(CommandHandler("reff", reff_command))
    application.add_handler(CommandHandler("convert", convert_to_txt_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(
        filters.Text(["☎️ Get Number", "Clear Prefix", "🏦 My Balance", "💸 Withdraw", "❓ Help", "Admin Panel"]),
        handle_main_menu_buttons
   ))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))

    await application.initialize()
    await application.start()
    if application.post_init:
        await application.post_init(application)
    
    logger.info("otp bot ready for use! developer @simpaticare")
    #asyncio.create_task(ivas_monitoring_task())

    for acc in ACCOUNTS:
        
         asyncio.create_task(worker(acc))
         await asyncio.sleep(2)

    await application.updater.start_polling(drop_pending_updates=True)

    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
