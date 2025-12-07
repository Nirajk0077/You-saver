import os

class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
    LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "0"))
    UPI_ID = os.environ.get("UPI_ID", "username@upi")
    UPI_PAYMENT_URL = os.environ.get("UPI_PAYMENT_URL", "https://example.com/qr")
