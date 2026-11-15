import time
import queue
import re
from typing import Optional, Dict
import requests
from instagrapi import Client
from instagrapi.types import DirectMessage
from database.models import (
    is_message_processed,
    is_url_processed,
    insert_reel,
    verify_registration,
    get_telegram_chat_for_user,
    get_registration_by_instagram
)
from instagram.extractor import extract_reel_url_from_message
from config import logger, TELEGRAM_BOT_TOKEN, INSTAGRAM_USERNAME, FORCE_SUB_INSTAGRAM

# Message types that can NEVER contain a Reel URL — safe to permanently mark as ignored
_DEFINITIVE_NON_REEL_TYPES = {
    "like", "reaction", "action_log", "profile", "placeholder",
    "raven_media", "voice_media", "animated_media", "story_share"
}

# Cache for follower status: {username: expiry_timestamp}
_FOLLOWER_CACHE: Dict[str, float] = {}

def is_user_following(cl: Client, username: str) -> bool:
    """
    Checks if an Instagram username is currently following the bot's account.
    Caches positive results for 10 minutes to minimize API requests.
    Fails open (returns True) on unexpected API errors to protect user experience.
    """
    if not cl or not username:
        return True
    
    username = username.strip().lower()
    now = time.time()
    
    # Check in-memory cache
    if username in _FOLLOWER_CACHE:
        if now < _FOLLOWER_CACHE[username]:
            return True
        else:
            del _FOLLOWER_CACHE[username]

    try:
        followers = cl.search_followers(cl.user_id, username)
        is_following = any(getattr(u, "username", "").lower() == username for u in followers)
        if is_following:
            _FOLLOWER_CACHE[username] = now + 600  # cache for 10 minutes
        return is_following
    except Exception as e:
        logger.warning(f"Error checking follower status for {username}: {e}")
        # Fail open on network/API glitch so legitimate users aren't blocked
        return True

def send_telegram_follow_warning(tg_chat_id: str) -> None:
    """Sends a notification to the user's Telegram chat asking them to follow on Instagram."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": tg_chat_id,
            "text": (
                "📢 <b>Instagram Follow Required!</b>\n\n"
                f"You must follow our Instagram account <a href=\"https://www.instagram.com/{INSTAGRAM_USERNAME}\">@{INSTAGRAM_USERNAME}</a> to use ʀᴇᴇʟɢʀᴀᴍ services!\n\n"
                f"👉 Please follow <a href=\"https://www.instagram.com/{INSTAGRAM_USERNAME}\">@{INSTAGRAM_USERNAME}</a> on Instagram and try again."
            ),
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.debug(f"Could not send Telegram follow warning to {tg_chat_id}: {e}")

def process_message_event(
    msg: DirectMessage,
    q: queue.Queue,
    sender_username: Optional[str] = None,
    cl: Optional[Client] = None,
    thread_id: Optional[str] = None
) -> None:
    """
    Evaluates an individual Instagram DirectMessage.
    Identifies Reel URLs, performs database checks for duplicate URLs and messages,
    enforces Instagram follow requirements, updates records, and pushes valid items to the worker queue.
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
            # Check Instagram Force-Follow if enabled
            if FORCE_SUB_INSTAGRAM and cl:
                if not is_user_following(cl, sender_username):
                    logger.warning(f"User @{sender_username} is not following @{INSTAGRAM_USERNAME}. Verification blocked.")
                    if thread_id:
                        try:
                            cl.direct_answer(
                                int(thread_id),
                                f"⚠️ Follow Required: You must follow @{INSTAGRAM_USERNAME} to link your account! Please follow us and send the code again."
                            )
                        except Exception as e:
                            logger.debug(f"Failed to send Instagram DM follow warning: {e}")
                    
                    tg_chat_id = get_telegram_chat_for_user(sender_username)
                    if not tg_chat_id:
                        reg = get_registration_by_instagram(sender_username)
                        if reg:
                            tg_chat_id = reg.get("telegram_chat_id")
                    if tg_chat_id:
                        send_telegram_follow_warning(tg_chat_id)
                    
                    insert_reel(msg.id, "N/A", "unfollowed_blocked", sender_username)
                    return

            if verify_registration(sender_username, code):
                logger.info(f"Instagram user {sender_username} verified successfully via code {code}")
                # Reset monitor back to normal interval now that verification succeeded
                try:
                    from instagram.monitor import get_instagram_monitor
                    monitor = get_instagram_monitor()
                    if monitor:
                        monitor.reset_to_normal_interval()
                except Exception:
                    pass

                # Send confirmation directly in Instagram DM
                if thread_id and cl:
                    try:
                        cl.direct_answer(
                            int(thread_id),
                            f"✅ Account Verified!\n\nYour Instagram @{sender_username} is now linked to your Telegram chat.\n\nSend any Reel here anytime and it will be delivered directly to your Telegram! ⚡"
                        )
                        logger.info(f"Sent Instagram DM verification response to thread {thread_id}")
                    except Exception as ie:
                        logger.warning(f"Could not send Instagram DM verification response: {ie}")

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
                # Notify in Instagram DM if verification code failed
                if thread_id and cl:
                    try:
                        cl.direct_answer(
                            int(thread_id),
                            "❌ Verification Failed: That code is invalid or has expired.\n\nPlease generate a new code using /register on Telegram and try again."
                        )
                    except Exception as ie:
                        logger.debug(f"Could not send Instagram DM failure reply: {ie}")
        
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

    # 5. Check Instagram Force-Follow for Reels
    if FORCE_SUB_INSTAGRAM and cl and sender_username:
        if not is_user_following(cl, sender_username):
            logger.warning(f"Reel ignored: User @{sender_username} is not following @{INSTAGRAM_USERNAME}.")
            if thread_id:
                try:
                    cl.direct_answer(
                        int(thread_id),
                        f"⚠️ Follow Required: You must follow @{INSTAGRAM_USERNAME} to receive Reels on Telegram! Please follow us first."
                    )
                except Exception as e:
                    logger.debug(f"Failed to send Instagram DM follow warning: {e}")
            
            tg_chat_id = get_telegram_chat_for_user(sender_username)
            if not tg_chat_id:
                reg = get_registration_by_instagram(sender_username)
                if reg:
                    tg_chat_id = reg.get("telegram_chat_id")
            if tg_chat_id:
                send_telegram_follow_warning(tg_chat_id)
            
            insert_reel(msg.id, "N/A", "unfollowed_blocked", sender_username)
            return

    # 6. Insert as pending and send to the queue for downloader/uploader workers
    insert_reel(msg.id, reel_url, "pending", sender_username)
    logger.info(f"Valid Reel detected: {reel_url}. Msg ID: {msg.id}. Queueing for worker processing.")

    q.put({
        "message_id": msg.id,
        "url": reel_url,
        "sender_username": sender_username
    })
