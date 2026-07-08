import time
import queue
import threading
import sys
import signal
from pathlib import Path
from config import validate_config, logger
from database.models import init_db, update_reel_status, get_pending_reels
from downloader.download import download_reel
from downloader.cleaner import clean_file
from telegram_bot.sender import send_video_sync
from instagram.login import login_to_instagram
from instagram.monitor import InstagramMonitor

# Global lists/objects to handle graceful shutdown
workers = []
worker_stop_event = threading.Event()
instagram_monitor = None
registration_bot = None

def worker_loop(task_queue: queue.Queue, stop_event: threading.Event) -> None:
    """
    Background worker loop that consumes processing tasks (Instagram Reel URLs) from the queue,
    downloads them using yt-dlp, uploads them via the Telegram Bot, and executes local cleanup.
    """
    thread_name = threading.current_thread().name
    logger.info(f"Worker thread {thread_name} initialized.")
    
    while not stop_event.is_set():
        try:
            # Poll the queue with a short timeout to periodically check the stop event
            task = task_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        message_id = task["message_id"]
        url = task["url"]
        logger.info(f"[{thread_name}] Processing task: MSG_ID={message_id}, URL={url}")

        video_path = None
        try:
            # 1. Update status to downloading and start download
            update_reel_status(message_id, status="downloading")
            video_path = download_reel(url)

            if not video_path or not Path(video_path).exists():
                logger.error(f"[{thread_name}] Download failed: No file found at target path for URL {url}")
                update_reel_status(message_id, status="download_failed")
                task_queue.task_done()
                continue

            # 2. Update status to uploading and start Telegram upload
            update_reel_status(message_id, status="uploading")
            
            sender_username = task.get("sender_username")
            target_chat_id = None
            if sender_username:
                from database.models import get_telegram_chat_for_user
                target_chat_id = get_telegram_chat_for_user(sender_username)
                if target_chat_id:
                    logger.info(f"[{thread_name}] Routing Reel for user @{sender_username} to Telegram chat: {target_chat_id}")
                else:
                    logger.warning(f"[{thread_name}] No linked Telegram chat found for Instagram user @{sender_username}. Falling back to default chat.")
            
            telegram_message_id = send_video_sync(video_path, url, chat_id=target_chat_id)

            # 3. Successful transaction: update DB and remove temp file
            update_reel_status(message_id, telegram_message_id=telegram_message_id, status="completed")
            clean_file(video_path)
            logger.info(f"[{thread_name}] Task successful: MSG_ID={message_id} -> Telegram MSG_ID={telegram_message_id}")

        except Exception as e:
            logger.error(f"[{thread_name}] Error processing Reel (MSG_ID={message_id}): {e}", exc_info=True)
            # Update status in the database to allow monitoring and potential manual retry
            update_reel_status(message_id, status="failed")
            # Note: We do NOT call clean_file(video_path) here. 
            # Per system requirements: "If upload fails: Keep file."
            
        finally:
            task_queue.task_done()

    logger.info(f"Worker thread {thread_name} shutting down.")

def handle_shutdown(signum, frame) -> None:
    """
    Handles terminal signals (SIGINT, SIGTERM) to initiate a graceful shutdown.
    """
    logger.info(f"Shutdown signal ({signum}) received. Initiating cleanup...")
    
    # 1. Stop Instagram Polling Monitor
    if instagram_monitor:
        instagram_monitor.stop()

    # 1b. Stop Telegram Registration Bot
    global registration_bot
    if registration_bot:
        registration_bot.stop()

    # 2. Stop Background Workers
    logger.info("Signaling background workers to stop...")
    worker_stop_event.set()

    # 3. Wait for workers to exit
    for w in workers:
        w.join(timeout=5)
        logger.info(f"Worker thread {w.name} joined.")

    logger.info("System cleanup complete. Exiting application.")
    sys.exit(0)

def main() -> None:
    """
    Main entrypoint of the automation system.
    Initializes configurations, database, logs, worker threads, and starts Instagram monitor.
    """
    global instagram_monitor, workers, worker_stop_event

    # Register signals for graceful termination
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    logger.info("Initializing Instagram Reel to Telegram Automation System...")

    try:
        # Validate environment configuration
        validate_config()

        # Create database and tables
        init_db()

        # Thread-safe queue for worker communications
        task_queue = queue.Queue()

        # Populate queue with any pending tasks from a previous run (crash recovery)
        pending_tasks = get_pending_reels()
        if pending_tasks:
            logger.info(f"Crash recovery: found {len(pending_tasks)} pending tasks in DB. Queuing them first...")
            for task in pending_tasks:
                task_queue.put(task)

        # Authenticate with Instagram API
        logger.info("Authenticating with Instagram...")
        instagram_client = login_to_instagram()

        # Spawn background workers (2 workers is standard for download/upload thread pools)
        num_workers = 2
        logger.info(f"Spawning {num_workers} background worker threads...")
        for i in range(num_workers):
            t = threading.Thread(
                target=worker_loop,
                args=(task_queue, worker_stop_event),
                name=f"DownloadWorker-{i+1}"
            )
            t.daemon = True
            t.start()
            workers.append(t)

        # Initialize and start Instagram monitor
        # Poll inbox threads every 30 seconds
        instagram_monitor = InstagramMonitor(instagram_client, task_queue, poll_interval=30)
        instagram_monitor.start()

        # Initialize and start Telegram registration bot
        global registration_bot
        from telegram_bot.registration_bot import RegistrationBot
        registration_bot = RegistrationBot()
        registration_bot.start()

        logger.info("System is fully running. Press Ctrl+C to terminate.")

        # Keep main thread alive
        while True:
            time.sleep(1)

    except Exception as e:
        logger.critical(f"System startup encountered a fatal error: {e}", exc_info=True)
        # Force a shutdown to release threads/resources
        handle_shutdown(signal.SIGABRT, None)

if __name__ == "__main__":
    main()
