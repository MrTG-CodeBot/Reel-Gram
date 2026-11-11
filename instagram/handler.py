"""
Instagram message event handler.
Processes incoming Direct Messages, handles verification codes for account linking,
verifies follower status, and queues media download requests.
"""

import re
import time
import queue
import requests
from typing import Optional
from instagrapi import Client
from instagrapi.types import DirectMessage
from database.models import (
    is_message_processed,
    insert_reel,
    verify_registration,
    get_telegram_chat_for_user,
    get_registration_by_instagram
)
from instagram.extractor import extract_media_url_and_direct
from config import (
    logger,
    INSTAGRAM_USERNAME,
    FORCE_SUB_INSTAGRAM,
    TELEGRAM_BOT_TOKEN
)

# Caches for follower lookups to minimize API rate limits
_FOLLOWER_CACHE = {}
_LAST_FOLLOWERS_FETCH = 0.0
_ALL_FOLLOWERS_CACHE = {}

# Dedup sets for warnings to prevent spamming users
_WARNED_FOLLOW_DM = set()
_WARNED_FOLLOW_TG = set()

_DEFINITIVE_NON_REEL_TYPES = {
    "voice_media",
    "animated_media",
    "felix_share",
    "placeholder"
}


def is_user_following(cl: Optional[Client], username: str, user_id: Optional[str] = None) -> bool:
    """
    Checks if an Instagram user is currently following the bot account.
    Employs short-lived in-memory caching and mobile API lookups.
    Fails open on unexpected network or API errors to avoid blocking legitimate users.
    """
    if not cl or not username:
        return True

    username = username.strip().lower()
    now = time.time()

    # Check recent positive cache
    if username in _FOLLOWER_CACHE:
        if now < _FOLLOWER_CACHE[username]:
            return True
        del _FOLLOWER_CACHE[username]

    global _LAST_FOLLOWERS_FETCH, _ALL_FOLLOWERS_CACHE

    if username in _ALL_FOLLOWERS_CACHE:
        _FOLLOWER_CACHE[username] = now + 600
        return True

    target_id = str(user_id) if user_id else _ALL_FOLLOWERS_CACHE.get(username)
    if not target_id:
        try:
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
                logger.info(f"Verified @{username} follows the bot via friendship API.")
                return True
        except Exception as e:
            api_errors += 1
            logger.warning(f"Direct friendship check failed for {username} ({target_id}): {e}")

    # Refresh full followers cache if stale
    if (now - _LAST_FOLLOWERS_FETCH > 20) or not _ALL_FOLLOWERS_CACHE:
        try:
            followers = cl.user_followers(cl.user_id)
            _ALL_FOLLOWERS_CACHE = {
                getattr(u, "username", "").lower(): str(pk)
                for pk, u in followers.items()
            }
            _LAST_FOLLOWERS_FETCH = now
            if username in _ALL_FOLLOWERS_CACHE:
                _FOLLOWER_CACHE[username] = now + 600
                logger.info(f"Verified @{username} follows the bot via followers list.")
                return True
        except Exception as fe:
            api_errors += 1
            logger.warning(f"Failed to fetch followers list: {fe}")

    # Fail open on multiple API errors (rate limits or network anomalies)
    if api_errors >= 2:
        logger.warning(f"Follower check APIs failed. Failing open for @{username}.")
        return True

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
    Detects media URLs, enforces follow rules, handles account linking codes,
    and forwards download tasks to the worker queue.
    """
    # Ignore messages sent by the bot itself
    if getattr(msg, "is_sent_by_viewer", False) or (cl and getattr(cl, "user_id", None) and str(msg.user_id) == str(cl.user_id)):
        return

    if sender_username and INSTAGRAM_USERNAME and sender_username.lower() == INSTAGRAM_USERNAME.lower():
        return

    if is_message_processed(msg.id):
        return

    item_type = getattr(msg, "item_type", "unknown") or "unknown"

    # Handle account linking verification codes (e.g., RG-123456)
    text = getattr(msg, "text", "") or ""
    verify_match = re.search(r"\bRG-\d{6}\b", text.strip().upper())
    if verify_match:
        code = verify_match.group(0)
        logger.info(f"Verification code '{code}' received from @{sender_username}")
        if sender_username:
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

                    return

            if verify_registration(sender_username, code):
                logger.info(f"Instagram user @{sender_username} verified successfully via code {code}")
                try:
                    from instagram.monitor import get_instagram_monitor
                    monitor = get_instagram_monitor()
                    if monitor:
                        monitor.reset_to_normal_interval()
                except Exception:
                    pass

                if thread_id and cl:
                    try:
                        cl.direct_answer(
                            int(thread_id),
                            f"✅ Account Verified!\n\nYour Instagram @{sender_username} is now linked to your Telegram chat.\n\nSend any Reel, Post, Story, or Highlight here anytime! ⚡"
                        )
                    except Exception as ie:
                        logger.warning(f"Could not send Instagram DM verification response: {ie}")

                tg_chat_id = get_telegram_chat_for_user(sender_username)
                if tg_chat_id:
                    try:
                        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                        payload = {
                            "chat_id": tg_chat_id,
                            "text": f"✅ Instagram account @{sender_username} has been verified and linked!\n\nSend media to my DM on Instagram to receive it here."
                        }
                        requests.post(url, json=payload, timeout=10)
                    except Exception as te:
                        logger.error(f"Failed to send Telegram confirmation: {te}")
            else:
                logger.warning(f"Verification failed for code '{code}' from @{sender_username}")
                if thread_id and cl:
                    try:
                        cl.direct_answer(
                            int(thread_id),
                            "❌ Verification Failed: That code is invalid or has expired.\n\nPlease generate a new code using /register on Telegram and try again."
                        )
                    except Exception as ie:
                        logger.debug(f"Could not send Instagram DM failure reply: {ie}")

        insert_reel(msg.id, "N/A", "verified_code", sender_username)
        return

    # Extract media link and optional direct CDN stream
    reel_url, direct_cdn_url = extract_media_url_and_direct(msg)
    if not reel_url:
        if item_type in _DEFINITIVE_NON_REEL_TYPES or item_type == "text":
            insert_reel(msg.id, "N/A", "ignored_not_reel", sender_username)
        return

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

    insert_reel(msg.id, reel_url, "pending", sender_username)
    logger.info(f"Queued media task: {reel_url} (ID: {msg.id})")

    q.put({
        "message_id": msg.id,
        "url": reel_url,
        "sender_username": sender_username,
        "direct_cdn_url": direct_cdn_url
    })
