import os

class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    MONGO_DB_URI = os.environ.get("MONGO_DB_URI", "mongodb+srv://ashokkumarraipur991_db_user:tBkZTT17BM1l9N5C@cluster0.fyaywqe.mongodb.net/?appName=Cluster0")
    LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", "-1003435284491"))
    # ADMIN_IDS: comma separated list of user IDs
    ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "8070498307").split(",") if x.isdigit()]
    CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/Deendayal_dhakadd")
