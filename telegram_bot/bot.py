"""
Telegram Bot client factory.
Initializes the python-telegram-bot instance with configured credentials.
"""

from telegram import Bot
from config import TELEGRAM_BOT_TOKEN


def get_telegram_bot() -> Bot:
    """Returns an initialized Telegram Bot instance using the configured bot token."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured.")
    return Bot(token=TELEGRAM_BOT_TOKEN)
