import os

class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    OWNER_ID = int(os.environ.get("OWNER_ID", "8070498307"))
    LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "-1003451702258"))
    UPI_ID = os.environ.get("UPI_ID", "deendayalsurajk@axl")
    UPI_PAYMENT_URL = os.environ.get("UPI_PAYMENT_URL", "https://i.ibb.co/671jvbNc/photo-2025-12-07-21-59-56-7581239201589362712.jpg")
    OWNER_CONTACT_URL = os.environ.get("OWNER_CONTACT_URL", "http://t.me/Sorry_Sorry_Galti_Ho_Gaii")
