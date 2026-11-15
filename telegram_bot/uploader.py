import asyncio
from pathlib import Path
from typing import Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, RetryAfter
from config import TELEGRAM_CHAT_ID, logger
from telegram_bot.bot import get_telegram_bot

async def upload_video_to_telegram(
    video_path: Path,
    reel_url: str,
    max_retries: int = 3,
    chat_id: Optional[str] = None,
    sender_username: Optional[str] = None
) -> str:
    """
    Asynchronously uploads the downloaded Reel video to the target Telegram chat.
    Attaches an inline button linking to the sender's Instagram profile.
    
    :param video_path: Path to the video file on local disk.
    :param reel_url: The original URL of the Instagram Reel.
    :param max_retries: Maximum number of upload attempts.
    :param chat_id: Telegram Chat ID override. If None, falls back to config.TELEGRAM_CHAT_ID.
    :param sender_username: Instagram username of the user who sent the Reel.
    :return: The message ID of the sent message on Telegram as a string.
    """
    target_chat = chat_id or TELEGRAM_CHAT_ID
    logger.info(f"Starting Telegram upload for video: {video_path} to chat: {target_chat} (sender: {sender_username})")

    reply_markup = None
    if sender_username:
        clean_user = sender_username.strip().replace("@", "").strip(".")
        if clean_user and clean_user.lower() != "n/a":
            profile_url = f"https://www.instagram.com/{clean_user}/"
            keyboard = [
                [InlineKeyboardButton(f"👤 Sent by: @{clean_user}", url=profile_url)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
    
    retry_delay = 5.0
    for attempt in range(1, max_retries + 1):
        try:
            bot = get_telegram_bot()
            # We initialize bot context manager to perform API calls securely
            async with bot:
                with open(video_path, "rb") as video_file:
                    message = await bot.send_video(
                        chat_id=target_chat,
                        video=video_file,
                        reply_markup=reply_markup,
                        read_timeout=120,
                        write_timeout=300,  # Generous write timeout for larger uploads
                        connect_timeout=60,
                        pool_timeout=60
                    )
                logger.info(f"Telegram upload succeeded on attempt {attempt}. Message ID: {message.message_id}")
                return str(message.message_id)
                
        except RetryAfter as e:
            delay = e.retry_after
            logger.warning(f"Telegram rate limit hit. Retrying in {delay}s (Attempt {attempt}/{max_retries}).")
            await asyncio.sleep(delay)
            
        except TelegramError as e:
            logger.error(f"Telegram API error on attempt {attempt}/{max_retries}: {e}")
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)
                retry_delay *= 2.0
            else:
                raise
                
        except Exception as e:
            logger.error(f"Unexpected error during Telegram upload on attempt {attempt}/{max_retries}: {e}")
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)
                retry_delay *= 2.0
            else:
                raise
                
    raise RuntimeError(f"Failed to upload Reel to Telegram after {max_retries} attempts.")

