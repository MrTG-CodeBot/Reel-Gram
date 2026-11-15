import queue
import re
from typing import Optional
import requests
from instagrapi.types import DirectMessage
from database.models import (
    is_message_processed,
    is_url_processed,
    insert_reel,
    verify_registration,
    get_telegram_chat_for_user
)
from instagram.extractor import extract_reel_url_from_message
from config import logger, TELEGRAM_BOT_TOKEN

# Message types that can NEVER contain a Reel URL — safe to permanently mark as ignored
_DEFINITIVE_NON_REEL_TYPES = {
    "like", "reaction", "action_log", "profile", "placeholder",
    "raven_media", "voice_media", "animated_media", "story_share"
}

def process_message_event(msg: DirectMessage, q: queue.Queue, sender_username: Optional[str] = None) -> None:
    """
    Evaluates an individual Instagram DirectMessage.
    Identifies Reel URLs, performs database checks for duplicate URLs and messages,
    updates database records, and appends valid items to the processing queue.
    """
    # 1. Skip messages sent by the bot account itself
    if getattr(msg, "is_sent_by_viewer", False):
        return

    # 2. Check if message ID has already been evaluated
    if is_message_processed(msg.id):
        return

    item_type = getattr(msg, "item_type", "unknown") or "unknown"
    logger.info(f"Evaluating message {msg.id} | item_type={item_type} | sender={sender_username}")

    # 3. Check for verification command (e.g., "verify RG-123456" or "RG-123456")
    text = getattr(msg, "text", "") or ""
    text_clean = text.strip().upper()
    verify_match = re.search(r"\bRG-\d{6}\b", text_clean)
    if verify_match:
        code = verify_match.group(0)
        logger.info(f"Verification code '{code}' detected from Instagram user: {sender_username}")
        if sender_username:
            if verify_registration(sender_username, code):
                logger.info(f"Instagram user {sender_username} verified successfully via code {code}")
                # Get the associated Telegram chat ID
                tg_chat_id = get_telegram_chat_for_user(sender_username)
                if tg_chat_id:
                    # Notify Telegram user
                    try:
                        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                        payload = {
                            "chat_id": tg_chat_id,
                            "text": f"✅ Instagram account https://www.instagram.com/{sender_username} has been successfully verified and linked!\n\nSend any Reel to my DM on Instagram to receive it here."
                        }
                        requests.post(url, json=payload, timeout=10)
                        logger.info(f"Sent Telegram verification confirmation to chat: {tg_chat_id}")
                    except Exception as te:
                        logger.error(f"Failed to send Telegram confirmation: {te}")
            else:
                logger.warning(f"Verification failed for code '{code}' from user: {sender_username}")
        
        # Mark the message as processed (so we don't re-check this verification code)
        insert_reel(msg.id, "N/A", "verified_code", sender_username)
        return

    # 4. Try to extract Reel URL
    reel_url = extract_reel_url_from_message(msg)
    if not reel_url:
        # Only permanently ignore types that definitively cannot carry a reel.
        # For potentially reel-bearing types (link, clip, media, reel_share, etc.)
        # we skip DB insertion so they can be re-evaluated next poll.
        if item_type in _DEFINITIVE_NON_REEL_TYPES or item_type == "text":
            insert_reel(msg.id, "N/A", "ignored_not_reel", sender_username)
            logger.debug(f"Message {msg.id} is type '{item_type}' — permanently ignored.")
        else:
            logger.info(f"Message {msg.id} (type={item_type}) had no reel URL this poll — will retry next poll.")
        return

    # 5. Insert as pending and send to the queue for downloader/uploader workers
    insert_reel(msg.id, reel_url, "pending", sender_username)
    logger.info(f"Valid Reel detected: {reel_url}. Msg ID: {msg.id}. Queueing for worker processing.")

    q.put({
        "message_id": msg.id,
        "url": reel_url,
        "sender_username": sender_username
    })
