import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")
INSTAGRAM_SESSION_ID = os.getenv("INSTAGRAM_SESSION_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DOWNLOAD_PATH_STR = os.getenv("DOWNLOAD_PATH", "downloads/")
LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "reelgram")

# Force Subscribe and Developer settings
FORCE_SUB_CHANNEL_ID = os.getenv("FORCE_SUB_CHANNEL_ID")
FORCE_SUB_INVITE_LINK = os.getenv("FORCE_SUB_INVITE_LINK", "https://t.me/telegram")
DEVELOPER_USERNAME = os.getenv("DEVELOPER_USERNAME", "developer")

# Owner settings
OWNER_ID = int(os.getenv("OWNER_ID", "0"))


# Resolve paths
DOWNLOAD_DIR = BASE_DIR / DOWNLOAD_PATH_STR
LOGS_DIR = BASE_DIR / "logs"

# Create necessary directories
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Set logging level
log_level = getattr(logging, LOG_LEVEL_STR, logging.INFO)

# Configure logging
log_file = LOGS_DIR / "app.log"
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s (%(threadName)s): %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding="utf-8")
    ]
)

logger = logging.getLogger("config")
logger.info("Logging configured successfully.")

def validate_config() -> None:
    """Validates that all required configuration values are present."""
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
        logger.error(f"Configuration validation failed. Missing variables: {missing}")
        raise ValueError(f"Missing required environment variables in .env: {', '.join(missing)}")
    
    logger.info("Configuration validation succeeded.")
