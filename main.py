import time
import queue
import threading
import sys
import signal
from pathlib import Path
from config import validate_config, logger
from database.models import init_db, update_reel_status, get_pending_reels
from downloader.download import download_media
from downloader.cleaner import clean_file
from telegram_bot.sender import send_media_sync
from instagram.login import login_to_instagram
from instagram.monitor import InstagramMonitor

# Global lists/objects to handle graceful shutdown
workers = []
worker_stop_event = threading.Event()
instagram_monitor = None
registration_bot = None

def worker_loop(task_queue: queue.Queue, stop_event: threading.Event, instagram_client=None) -> None:
    """
    Background worker loop that consumes processing tasks (Instagram Reel, Post, Carousel, Story, or Highlight URLs)
    from the queue, downloads them, uploads them to Telegram, and executes local cleanup.
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

        media_files = []
        target_chat_id = None
        sender_username = task.get("sender_username")
        if sender_username:
            from database.models import get_telegram_chat_for_user
            target_chat_id = get_telegram_chat_for_user(sender_username)
            if target_chat_id:
                logger.info(f"[{thread_name}] Routing media for user @{sender_username} to Telegram chat: {target_chat_id}")
            else:
                logger.warning(f"[{thread_name}] No linked Telegram chat found for Instagram user @{sender_username}. Falling back to default chat.")

        try:
            # 1. Update status to downloading and start download
            update_reel_status(message_id, status="downloading", telegram_chat_id=target_chat_id)
            media_files = download_media(url, cl=instagram_client)

            if not media_files:
                logger.error(f"[{thread_name}] Download failed: No file found at target path for URL {url}")
                update_reel_status(message_id, status="download_failed", telegram_chat_id=target_chat_id)
                task_queue.task_done()
                continue

            # 2. Update status to uploading and start Telegram upload
            update_reel_status(message_id, status="uploading", telegram_chat_id=target_chat_id)
            
            telegram_message_id = send_media_sync(media_files, url, chat_id=target_chat_id, sender_username=sender_username)

            # 3. Successful transaction: update DB and remove temp files
            update_reel_status(message_id, telegram_message_id=telegram_message_id, status="completed", telegram_chat_id=target_chat_id)
            clean_file(media_files)
            logger.info(f"[{thread_name}] Task successful: MSG_ID={message_id} -> Telegram MSG_ID={telegram_message_id}")

        except Exception as e:
            logger.error(f"[{thread_name}] Error processing media (MSG_ID={message_id}): {e}", exc_info=True)
            # Update status in the database to allow monitoring and potential manual retry
            update_reel_status(message_id, status="failed", telegram_chat_id=target_chat_id)
            
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

def start_health_server() -> None:
    """
    Starts a lightweight HTTP server on $PORT for Render/cloud web service compatibility.
    Allows running on Render's 100% Free Web Service tier.
    """
    import os
    port_str = os.getenv("PORT")
    if not port_str and not os.getenv("RENDER"):
        return

    port = int(port_str) if port_str and port_str.isdigit() else 8080
    import http.server
    import socketserver

    class HealthHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","service":"reelgram"}')

        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()

        def log_message(self, format, *args):
            pass

    try:
        httpd = socketserver.TCPServer(("", port), HealthHandler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True, name="HealthCheckServer")
        t.start()
        logger.info(f"Health check HTTP server started on port {port} (Render compatible).")
    except Exception as e:
        logger.warning(f"Could not start health check server on port {port}: {e}")

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

        # Start health check server if running on cloud/Render
        start_health_server()

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
                args=(task_queue, worker_stop_event, instagram_client),
                name=f"DownloadWorker-{i+1}"
            )
            t.daemon = True
            t.start()
            workers.append(t)

        # Initialize and start Instagram monitor (polls inbox every 12s normally, 4s during registration)
        instagram_monitor = InstagramMonitor(instagram_client, task_queue, poll_interval=12)
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
