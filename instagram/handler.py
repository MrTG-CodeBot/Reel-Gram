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
from instagram.extractor import extract_media_url_and_direct, extract_reel_url_from_message
from config import logger, TELEGRAM_BOT_TOKEN, INSTAGRAM_USERNAME, FORCE_SUB_INSTAGRAM

# Message types that can NEVER contain any media — safe to permanently mark as ignored
_DEFINITIVE_NON_REEL_TYPES = {
    "like", "reaction", "action_log", "profile", "placeholder",
    "raven_media", "voice_media", "animated_media"
}

# Cache for follower status: {username: expiry_timestamp}
_FOLLOWER_CACHE: Dict[str, float] = {}
_ALL_FOLLOWERS_CACHE: Dict[str, str] = {}  # {username_lower: user_id}
_LAST_FOLLOWERS_FETCH: float = 0.0

# Sets to avoid spamming the same warning repeatedly for the exact same message ID
_WARNED_FOLLOW_DM: set = set()
_WARNED_FOLLOW_TG: set = set()

def is_user_following(cl: Client, username: str, user_id: Optional[str] = None) -> bool:
    """
    Checks if an Instagram username or user_id is currently following the bot's account.
    Uses multiple reliable methods:
    1. Fast in-memory positive cache (10 minutes)
    2. Direct friendship API (cl.user_friendship_v1) using target user ID
    3. Cached full followers list (cl.user_followers)
    Fails open (returns True) on unexpected network/API errors to ensure legitimate users are never blocked.
    """
    if not cl or not username:
        return True
    
    username = username.strip().lower()
    now = time.time()
    
    # 1. Check positive in-memory cache
    if username in _FOLLOWER_CACHE:
        if now < _FOLLOWER_CACHE[username]:
            return True
        else:
            del _FOLLOWER_CACHE[username]

    global _LAST_FOLLOWERS_FETCH, _ALL_FOLLOWERS_CACHE

    # 2. Check full followers cache if recently populated
    if username in _ALL_FOLLOWERS_CACHE:
        _FOLLOWER_CACHE[username] = now + 600
        return True

    # 3. Direct check via friendship API if user_id is provided or can be found
    target_id = str(user_id) if user_id else _ALL_FOLLOWERS_CACHE.get(username)
    if not target_id:
        try:
            # Use private mobile API endpoint to resolve user_id safely without web scraping
            u_info = cl.user_info_by_username_v1(username)
            if u_info and getattr(u_info, "pk", None):
                target_id = str(u_info.pk)
        except Exception as e:
            logger.debug(f"Could not resolve user ID for {username}: {e}")

    api_errors = 0
    if target_id:
        try:
            rel = cl.user_friendship_v1(target_id)
            if rel and getattr(rel, "followed_by", False):
                _FOLLOWER_CACHE[username] = now + 600
                logger.info(f"Confirmed user @{username} (ID: {target_id}) follows the bot via friendship API.")
                return True
        except Exception as e:
            api_errors += 1
            logger.warning(f"Direct friendship check failed for {username} ({target_id}): {e}")

    # 4. Refresh full followers list if cache is stale (>20s) or user wasn't verified yet
    if (now - _LAST_FOLLOWERS_FETCH > 20) or not _ALL_FOLLOWERS_CACHE:
        try:
            logger.info("Refreshing Instagram bot followers list to update cache...")
            followers = cl.user_followers(cl.user_id)
            _ALL_FOLLOWERS_CACHE = {
                getattr(u, "username", "").lower(): str(pk)
                for pk, u in followers.items()
            }
            _LAST_FOLLOWERS_FETCH = now
            if username in _ALL_FOLLOWERS_CACHE:
                _FOLLOWER_CACHE[username] = now + 600
                logger.info(f"Confirmed user @{username} follows the bot via followers list.")
                return True
        except Exception as fe:
            api_errors += 1
            logger.warning(f"Failed to fetch followers list: {fe}")

    # If Instagram API failed on both checks (e.g. rate limit, challenge, network error), fail open
    if api_errors >= 2:
        logger.warning(f"Instagram follow verification APIs failed due to network/rate-limit. Failing open for @{username}.")
        return True

    # 5. If neither confirmed, user is not following
    return False

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
    if getattr(msg, "is_sent_by_viewer", False) or (cl and getattr(cl, "user_id", None) and str(msg.user_id) == str(cl.user_id)):
        return

    # Skip if message was from the bot's own username
    if sender_username and INSTAGRAM_USERNAME and sender_username.lower() == INSTAGRAM_USERNAME.lower():
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
                user_pk = getattr(msg, "user_id", None)
                if not is_user_following(cl, sender_username, user_id=user_pk):
                    logger.warning(f"User @{sender_username} is not following @{INSTAGRAM_USERNAME}. Verification held.")
                    if thread_id and msg.id not in _WARNED_FOLLOW_DM:
                        _WARNED_FOLLOW_DM.add(msg.id)
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
                    if tg_chat_id and msg.id not in _WARNED_FOLLOW_TG:
                        _WARNED_FOLLOW_TG.add(msg.id)
                        send_telegram_follow_warning(tg_chat_id)
                    
                    # Do not mark as permanently processed so if user clicks Follow on Instagram,
                    # the next poll will pick it up and complete the verification seamlessly
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

    # 4. Try to extract media URL (and direct CDN URL if available)
    reel_url, direct_cdn_url = extract_media_url_and_direct(msg)
    if not reel_url:
        # Only permanently ignore types that definitively cannot carry a reel.
        # For potentially reel-bearing types (link, clip, media, reel_share, story_share, etc.)
        # we skip DB insertion so they can be re-evaluated next poll.
        if item_type in _DEFINITIVE_NON_REEL_TYPES or item_type == "text":
            insert_reel(msg.id, "N/A", "ignored_not_reel", sender_username)
            logger.debug(f"Message {msg.id} is type '{item_type}' — permanently ignored.")
        else:
            logger.info(f"Message {msg.id} (type={item_type}) had no media URL this poll — will retry next poll.")
        return

    # 5. Check Instagram Force-Follow for Reels
    if FORCE_SUB_INSTAGRAM and cl and sender_username:
        user_pk = getattr(msg, "user_id", None)
        if not is_user_following(cl, sender_username, user_id=user_pk):
            logger.warning(f"Media ignored: User @{sender_username} is not following @{INSTAGRAM_USERNAME}.")
            if thread_id and msg.id not in _WARNED_FOLLOW_DM:
                _WARNED_FOLLOW_DM.add(msg.id)
                try:
                    cl.direct_answer(
                        int(thread_id),
                        f"⚠️ Follow Required: You must follow @{INSTAGRAM_USERNAME} to receive media on Telegram! Please follow us first."
                    )
                except Exception as e:
                    logger.debug(f"Failed to send Instagram DM follow warning: {e}")
            
            tg_chat_id = get_telegram_chat_for_user(sender_username)
            if not tg_chat_id:
                reg = get_registration_by_instagram(sender_username)
                if reg:
                    tg_chat_id = reg.get("telegram_chat_id")
            if tg_chat_id and msg.id not in _WARNED_FOLLOW_TG:
                _WARNED_FOLLOW_TG.add(msg.id)
                send_telegram_follow_warning(tg_chat_id)
            
            insert_reel(msg.id, "N/A", "unfollowed_blocked", sender_username)
            return

    # 6. Insert as pending and send to the queue for downloader/uploader workers
    insert_reel(msg.id, reel_url, "pending", sender_username)
    logger.info(f"Valid media detected: {reel_url}. Msg ID: {msg.id}. Queueing for worker processing.")

    q.put({
        "message_id": msg.id,
        "url": reel_url,
        "sender_username": sender_username,
        "direct_cdn_url": direct_cdn_url
    })
