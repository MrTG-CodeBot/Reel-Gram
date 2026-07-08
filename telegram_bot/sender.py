import asyncio
from pathlib import Path
from typing import Optional
from telegram_bot.uploader import upload_video_to_telegram
from config import logger

def send_video_sync(video_path: Path, reel_url: str, chat_id: Optional[str] = None) -> str:
    """
    Synchronously runs the async upload_video_to_telegram function.
    Handles event loop setup safely, making it callable from synchronous worker threads.
    
    :param video_path: Path to the local video file.
    :param reel_url: The original Instagram Reel URL.
    :param chat_id: Optional target Telegram chat ID override.
    :return: The Telegram message ID.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        # Create a new event loop for this thread if one doesn't exist
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        # In the off chance that this thread's event loop is already running,
        # run the coroutine using run_coroutine_threadsafe.
        logger.debug("Event loop is already running in this thread. Running task threadsafe...")
        future = asyncio.run_coroutine_threadsafe(upload_video_to_telegram(video_path, reel_url, chat_id=chat_id), loop)
        return future.result()
    else:
        logger.debug("Starting event loop to perform Telegram upload...")
        return loop.run_until_complete(upload_video_to_telegram(video_path, reel_url, chat_id=chat_id))
