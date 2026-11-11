"""
Application configuration and environment variable management.
Loads credentials, paths, MongoDB parameters, and sets up logging.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Instagram credentials
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")
INSTAGRAM_SESSION_ID = os.getenv("INSTAGRAM_SESSION_ID")

# Telegram credentials
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DOWNLOAD_PATH_STR = os.getenv("DOWNLOAD_PATH", "downloads/")
LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()

# Database settings
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "reelgram")

# Subscription & channel verification
FORCE_SUB_CHANNEL_ID = os.getenv("FORCE_SUB_CHANNEL_ID")
FORCE_SUB_INVITE_LINK = os.getenv("FORCE_SUB_INVITE_LINK", "https://t.me/telegram")
FORCE_SUB_INSTAGRAM = os.getenv("FORCE_SUB_INSTAGRAM", "true").lower() in ("true", "1", "yes")
DEVELOPER_USERNAME = os.getenv("DEVELOPER_USERNAME", "developer")

# Admin and ownership access control
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
ADMIN_IDS = {OWNER_ID} if OWNER_ID else set()
_raw_admin_ids = os.getenv("ADMIN_IDS", "") or os.getenv("ADMINS", "")
if _raw_admin_ids:
    for aid in _raw_admin_ids.split(","):
        aid = aid.strip()
        if aid.isdigit():
            ADMIN_IDS.add(int(aid))


def is_admin(user_id: int) -> bool:
    """Checks whether a Telegram user ID has admin or owner privileges."""
    if not user_id:
        return False
    return user_id in ADMIN_IDS or (OWNER_ID != 0 and user_id == OWNER_ID)


# Optional channel for logging user events and statistics
_raw_log_channel = os.getenv("LOG_CHANNEL_ID") or os.getenv("LOG_CHANNEL")
if _raw_log_channel and (_raw_log_channel.strip().startswith("-") or _raw_log_channel.strip().isdigit()):
    try:
        LOG_CHANNEL_ID = int(_raw_log_channel.strip())
    except ValueError:
        LOG_CHANNEL_ID = _raw_log_channel.strip()
else:
    LOG_CHANNEL_ID = _raw_log_channel.strip() if _raw_log_channel else None

# Local storage paths
DOWNLOAD_DIR = BASE_DIR / DOWNLOAD_PATH_STR
LOGS_DIR = BASE_DIR / "logs"

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

log_level = getattr(logging, LOG_LEVEL_STR, logging.INFO)
log_file = LOGS_DIR / "app.log"

logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s (%(threadName)s): %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding="utf-8")
    ]
)

logger = logging.getLogger("reelgram")


def validate_config() -> None:
    """
    Validates essential configuration parameters on application startup.
    Raises ValueError if any required credential is missing.
    """
    missing = []
    if not INSTAGRAM_USERNAME:
        missing.append("INSTAGRAM_USERNAME")
    if not INSTAGRAM_PASSWORD and not INSTAGRAM_SESSION_ID:
        missing.append("INSTAGRAM_PASSWORD or INSTAGRAM_SESSION_ID")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        logger.error(f"Missing required environment variables: {missing}")
        raise ValueError(f"Missing required environment variables in .env: {', '.join(missing)}")
