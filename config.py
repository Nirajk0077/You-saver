import os

class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    MONGO_DB_URI = os.environ.get("MONGO_DB_URI", "")
    LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", "0"))
    # ADMIN_IDS: comma separated list of user IDs
    ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.isdigit()]
    CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "")
