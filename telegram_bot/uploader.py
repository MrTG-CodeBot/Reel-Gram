import asyncio
from pathlib import Path
from typing import Optional, List, Union
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from telegram.error import TelegramError, RetryAfter
from config import TELEGRAM_CHAT_ID, logger
from telegram_bot.bot import get_telegram_bot

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov"}
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

async def upload_media_to_telegram(
    media_files: Union[Path, str, List[Path]],
    media_url: str,
    max_retries: int = 3,
    chat_id: Optional[str] = None,
    sender_username: Optional[str] = None
) -> str:
    """
    Asynchronously uploads downloaded Instagram media (Reel, Post, Carousel Album, Story, or Highlight)
    to the target Telegram chat.
    
    Supports:
    - Single Video (.mp4) -> send_video
    - Single Photo (.jpg/.png) -> send_photo
    - Carousel Album (multiple photos/videos) -> send_media_group
    """
    target_chat = chat_id or TELEGRAM_CHAT_ID
    
    if isinstance(media_files, (str, Path)):
        files = [Path(media_files)]
    else:
        files = [Path(f) for f in media_files if Path(f).exists()]

    if not files:
        raise FileNotFoundError("No valid media files found to upload to Telegram.")

    logger.info(f"Starting Telegram upload of {len(files)} file(s) to chat: {target_chat} (sender: {sender_username})")

    # Build caption & inline button
    clean_user = ""
    reply_markup = None
    caption_text = None
    
    if sender_username:
        clean_user = sender_username.strip().replace("@", "").strip(".")
        if clean_user and clean_user.lower() != "n/a":
            profile_url = f"https://www.instagram.com/{clean_user}/"
            keyboard = [
                [InlineKeyboardButton(f"👤 Sent by: @{clean_user}", url=profile_url)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            caption_text = f"👤 <b>Sent by:</b> <a href=\"{profile_url}\">@{clean_user}</a>"

    retry_delay = 5.0
    for attempt in range(1, max_retries + 1):
        try:
            bot = get_telegram_bot()
            async with bot:
                # CASE 1: Single Video
                if len(files) == 1 and files[0].suffix.lower() in VIDEO_EXTENSIONS:
                    with open(files[0], "rb") as video_file:
                        message = await bot.send_video(
                            chat_id=target_chat,
                            video=video_file,
                            caption=caption_text,
                            parse_mode="HTML",
                            reply_markup=reply_markup,
                            read_timeout=120,
                            write_timeout=300,
                            connect_timeout=60,
                            pool_timeout=60
                        )
                    logger.info(f"Telegram single video upload succeeded. Msg ID: {message.message_id}")
                    return str(message.message_id)

                # CASE 2: Single Photo
                elif len(files) == 1 and files[0].suffix.lower() in PHOTO_EXTENSIONS:
                    with open(files[0], "rb") as photo_file:
                        message = await bot.send_photo(
                            chat_id=target_chat,
                            photo=photo_file,
                            caption=caption_text,
                            parse_mode="HTML",
                            reply_markup=reply_markup,
                            read_timeout=120,
                            write_timeout=300,
                            connect_timeout=60,
                            pool_timeout=60
                        )
                    logger.info(f"Telegram single photo upload succeeded. Msg ID: {message.message_id}")
                    return str(message.message_id)

                # CASE 3: Multi-item Carousel / Album (send_media_group)
                else:
                    logger.info(f"Uploading carousel album ({len(files)} items) via send_media_group...")
                    sent_msg_ids = []
                    
                    # Telegram limits media groups to 10 items per batch
                    for batch_idx in range(0, len(files), 10):
                        batch = files[batch_idx:batch_idx + 10]
                        media_group = []
                        
                        # We must hold file descriptors open while send_media_group runs
                        file_handles = []
                        try:
                            for idx, fpath in enumerate(batch):
                                fh = open(fpath, "rb")
                                file_handles.append(fh)
                                is_first = (batch_idx == 0 and idx == 0)
                                cap = caption_text if is_first else None
                                
                                if fpath.suffix.lower() in VIDEO_EXTENSIONS:
                                    media_group.append(InputMediaVideo(media=fh, caption=cap, parse_mode="HTML"))
                                else:
                                    media_group.append(InputMediaPhoto(media=fh, caption=cap, parse_mode="HTML"))

                            msgs = await bot.send_media_group(
                                chat_id=target_chat,
                                media=media_group,
                                read_timeout=180,
                                write_timeout=360,
                                connect_timeout=60
                            )
                            if msgs:
                                sent_msg_ids.append(str(msgs[0].message_id))
                        finally:
                            for fh in file_handles:
                                try:
                                    fh.close()
                                except Exception:
                                    pass

                    logger.info(f"Telegram carousel upload succeeded. Msg IDs: {sent_msg_ids}")
                    return sent_msg_ids[0] if sent_msg_ids else "ok"

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

    raise RuntimeError(f"Failed to upload media to Telegram after {max_retries} attempts.")

# Backwards compatibility alias
upload_video_to_telegram = upload_media_to_telegram
