"""
Instagram authentication module.
Handles session persistence via session.json, session ID logins,
and credential-based logins using the instagrapi client.
"""

from pathlib import Path
from instagrapi import Client
from config import INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD, INSTAGRAM_SESSION_ID, logger

SESSION_FILE = Path("session.json")


def login_to_instagram() -> Client:
    """
    Authenticates with Instagram.
    Attempts to restore a cached session from session.json first.
    If unavailable or expired, authenticates via Session ID or username/password.
    """
    cl = Client()
    cl.delay_range = [1, 3]

    if SESSION_FILE.exists():
        logger.info("Found cached session. Attempting to restore...")
        try:
            cl.load_settings(SESSION_FILE)
            if cl.user_id:
                logger.info(f"Restored session for user ID: {cl.user_id}")
                return cl
        except Exception as e:
            logger.warning(f"Failed to restore cached session: {e}. Attempting fresh login.")

    if INSTAGRAM_SESSION_ID:
        logger.info("Logging in via Session ID...")
        try:
            cl.login_by_sessionid(INSTAGRAM_SESSION_ID)
            if cl.user_id:
                cl.dump_settings(SESSION_FILE)
                logger.info(f"Authenticated via Session ID (User ID: {cl.user_id})")
                return cl
        except Exception as e:
            logger.warning(f"Session ID login failed: {e}. Falling back to credentials...")

    if INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD:
        logger.info(f"Authenticating with credentials for @{INSTAGRAM_USERNAME}...")
        try:
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            cl.dump_settings(SESSION_FILE)
            logger.info("Credentials authentication successful. Saved session.")
            return cl
        except Exception as e:
            logger.critical(f"Instagram credentials login failed: {e}")
            raise RuntimeError("Instagram login failed.") from e

    raise RuntimeError("Instagram login failed: no valid credentials or session ID provided.")
