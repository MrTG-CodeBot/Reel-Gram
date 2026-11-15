"""
Synchronous wrapper for Telegram uploads.
Manages the asyncio event loop to allow multi-threaded worker pipelines
to safely trigger asynchronous media uploads.
"""

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
    Synchronously dispatches media upload tasks to Telegram.
    Safely integrates with active or newly spawned asyncio event loops.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        future = asyncio.run_coroutine_threadsafe(
            upload_media_to_telegram(media_files, media_url, chat_id=chat_id, sender_username=sender_username),
            loop
        )
        return future.result()

    return loop.run_until_complete(
        upload_media_to_telegram(media_files, media_url, chat_id=chat_id, sender_username=sender_username)
    )


send_video_sync = send_media_sync
