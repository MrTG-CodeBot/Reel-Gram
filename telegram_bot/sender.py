import asyncio
from pathlib import Path
from typing import Optional, List, Union
from telegram_bot.uploader import upload_media_to_telegram
from config import logger

def send_media_sync(
    media_files: Union[Path, str, List[Path]],
    media_url: str,
    chat_id: Optional[str] = None,
    sender_username: Optional[str] = None
) -> str:
    """
    Synchronously runs the async upload_media_to_telegram function.
    Handles event loop setup safely, making it callable from synchronous worker threads.
    Supports single videos, single photos, and carousel albums.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        logger.debug("Event loop is already running in this thread. Running task threadsafe...")
        future = asyncio.run_coroutine_threadsafe(
            upload_media_to_telegram(media_files, media_url, chat_id=chat_id, sender_username=sender_username),
            loop
        )
        return future.result()
    else:
        logger.debug("Starting event loop to perform Telegram upload...")
        return loop.run_until_complete(
            upload_media_to_telegram(media_files, media_url, chat_id=chat_id, sender_username=sender_username)
        )

# Backwards compatibility alias
send_video_sync = send_media_sync
