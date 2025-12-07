import os

class Config:
    API_ID = int(os.environ.get("API_ID", "29285954"))
    API_HASH = os.environ.get("API_HASH", "ee47f0d64723ee82fe3968ab09efbe3c")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "8481420396:AAHmjq0q6bR5BBYrIyTpk1pybiW2LE0amX8")
    OWNER_ID = int(os.environ.get("OWNER_ID", "8070498307"))
    LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "-1003451702258"))
    UPI_ID = os.environ.get("UPI_ID", "deendayalsurajk@axl")
    UPI_PAYMENT_URL = os.environ.get("UPI_PAYMENT_URL", "https://i.ibb.co/671jvbNc/photo-2025-12-07-21-59-56-7581239201589362712.jpg")
