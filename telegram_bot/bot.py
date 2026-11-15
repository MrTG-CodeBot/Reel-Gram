from telegram import Bot
from config import TELEGRAM_BOT_TOKEN

def get_telegram_bot() -> Bot:
    """
    Initializes and returns a Telegram Bot instance using the token
    configured in environment settings.
    """
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured.")
    return Bot(token=TELEGRAM_BOT_TOKEN)
