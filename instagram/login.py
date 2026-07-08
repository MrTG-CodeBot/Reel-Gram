import json
from pathlib import Path
from instagrapi import Client
from config import INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD, INSTAGRAM_SESSION_ID, logger

# Locate session.json in the project root
SESSION_FILE = Path("session.json")

def login_to_instagram() -> Client:
    """
    Authenticates with Instagram using instagrapi.
    Attempts to restore a saved session from session.json first.
    If restoring fails or session doesn't exist, logs in using Session ID or credentials
    and caches the session.
    """
    cl = Client()
    cl.delay_range = [1, 3]  # Simulates human interaction delay to prevent flags
    
    if SESSION_FILE.exists():
        logger.info("Found cached Instagram session settings. Attempting to restore...")
        try:
            cl.load_settings(SESSION_FILE)
            # Verify if loaded session settings are valid by checking the viewer user ID
            if cl.user_id:
                logger.info(f"Instagram session restored successfully (User ID: {cl.user_id}).")
                return cl
        except Exception as e:
            logger.warning(f"Failed to restore Instagram session: {e}. Will attempt fresh login.")

    # Try Session ID authentication if configured
    if INSTAGRAM_SESSION_ID:
        logger.info("Attempting Instagram login via Session ID...")
        try:
            cl.login_by_sessionid(INSTAGRAM_SESSION_ID)
            if cl.user_id:
                cl.dump_settings(SESSION_FILE)
                logger.info(f"Successfully authenticated via Session ID and saved session. User ID: {cl.user_id}")
                return cl
        except Exception as e:
            logger.warning(f"Session ID login failed: {e}. Falling back to credentials login...")

    # Cache didn't work or didn't exist. Attempt username/password login.
    if INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD:
        logger.info(f"Performing fresh Instagram login for username: {INSTAGRAM_USERNAME}")
        try:
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            # Cache the session settings for future startup
            cl.dump_settings(SESSION_FILE)
            logger.info("Successfully logged in and saved session settings to session.json.")
            return cl
        except Exception as e:
            logger.critical(f"Instagram login failed with credentials. Error: {e}")
            logger.critical("Check your credentials in .env. If 2FA is active, you may need to disable it or solve a challenge.")
            raise RuntimeError("Instagram login failed.") from e
    else:
        logger.critical("No valid authentication method found (neither Session ID nor credentials configured correctly).")
        raise RuntimeError("Instagram login failed: configuration incomplete.")

