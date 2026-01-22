import os

class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/Deendayal_dhakadd")
    MONGO_DB_URI = os.environ.get("MONGO_DB_URI", "")
    LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", "-1003451702258"))
    FSUB_CHANNEL_ID = int(os.environ.get("FSUB_CHANNEL_ID", "-1002568854373"))
    try:
        ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split()]
    except ValueError:
        ADMIN_IDS = []
