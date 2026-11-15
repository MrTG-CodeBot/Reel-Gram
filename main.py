"""
ReelGram application entrypoint.
Coordinates service startup, worker thread pools, crash recovery,
the Instagram inbox polling monitor, and the Telegram registration bot.
"""

import sys
import time
import queue
import signal
import threading
from typing import List

from config import validate_config, logger
from database.models import init_db, update_reel_status, get_pending_reels
from instagram.login import login_to_instagram
from instagram.monitor import InstagramMonitor
from downloader.download import download_media
from downloader.cleaner import clean_file
from telegram_bot.sender import send_media_sync

instagram_monitor: InstagramMonitor = None
workers: List[threading.Thread] = []
worker_stop_event = threading.Event()
registration_bot = None


def worker_loop(task_queue: queue.Queue, stop_event: threading.Event, instagram_client=None) -> None:
    """
    Worker consumer thread that retrieves download tasks from the queue,
    downloads media, uploads to Telegram, and cleans up local temporary files.
    """
    thread_name = threading.current_thread().name
    logger.info(f"Worker thread {thread_name} started.")

    while not stop_event.is_set():
        try:
            task = task_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        message_id = task["message_id"]
        url = task["url"]
        direct_cdn_url = task.get("direct_cdn_url")
        logger.info(f"[{thread_name}] Processing task: MSG_ID={message_id}, URL={url}")

        media_files = []
        target_chat_id = None
        sender_username = task.get("sender_username")
        if sender_username:
            from database.models import get_telegram_chat_for_user
            target_chat_id = get_telegram_chat_for_user(sender_username)
            if target_chat_id:
                logger.info(f"[{thread_name}] Routing media for @{sender_username} to Telegram chat: {target_chat_id}")
            else:
                logger.warning(f"[{thread_name}] No linked chat for @{sender_username}. Using default chat.")

        try:
            update_reel_status(message_id, status="downloading", telegram_chat_id=target_chat_id)
            media_files = download_media(url, cl=instagram_client, direct_url=direct_cdn_url)

            if not media_files:
                logger.error(f"[{thread_name}] Download yielded no files for URL: {url}")
                update_reel_status(message_id, status="download_failed", telegram_chat_id=target_chat_id)
                task_queue.task_done()
                continue

            update_reel_status(message_id, status="uploading", telegram_chat_id=target_chat_id)
            telegram_message_id = send_media_sync(
                media_files,
                url,
                chat_id=target_chat_id,
                sender_username=sender_username
            )

            update_reel_status(
                message_id,
                telegram_message_id=telegram_message_id,
                status="completed",
                telegram_chat_id=target_chat_id
            )
            clean_file(media_files)
            logger.info(f"[{thread_name}] Completed task {message_id} -> Telegram message {telegram_message_id}")

        except Exception as e:
            logger.error(f"[{thread_name}] Error processing task {message_id}: {e}", exc_info=True)
            update_reel_status(message_id, status="failed", telegram_chat_id=target_chat_id)

        finally:
            task_queue.task_done()

    logger.info(f"Worker thread {thread_name} exiting.")


def handle_shutdown(signum, frame) -> None:
    """Catches termination signals (SIGINT, SIGTERM) to cleanly stop threads and background bots."""
    logger.info(f"Received termination signal ({signum}). Initiating shutdown...")

    if instagram_monitor:
        instagram_monitor.stop()

    global registration_bot
    if registration_bot:
        registration_bot.stop()

    worker_stop_event.set()
    for w in workers:
        w.join(timeout=5)

    logger.info("Shutdown complete. Exiting.")
    sys.exit(0)


def start_health_server() -> None:
    """
    Starts a minimal HTTP health check server on $PORT for cloud hosting compatibility
    (e.g., Render, Railway, or Koyeb free web tiers).
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
        logger.info(f"Health check server active on port {port}.")
    except Exception as e:
        logger.warning(f"Could not start health check server on port {port}: {e}")


def main() -> None:
    """Bootstraps application components, loads pending tasks, and starts services."""
    global instagram_monitor, workers, worker_stop_event

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    logger.info("Starting ReelGram automation service...")

    try:
        validate_config()
        start_health_server()
        init_db()

        task_queue = queue.Queue()

        # Re-enqueue pending or interrupted tasks from database
        pending_tasks = get_pending_reels()
        if pending_tasks:
            logger.info(f"Recovered {len(pending_tasks)} pending task(s) from database.")
            for task in pending_tasks:
                task_queue.put(task)

        instagram_client = login_to_instagram()

        num_workers = 2
        for i in range(num_workers):
            t = threading.Thread(
                target=worker_loop,
                args=(task_queue, worker_stop_event, instagram_client),
                name=f"Worker-{i+1}"
            )
            t.daemon = True
            t.start()
            workers.append(t)

        instagram_monitor = InstagramMonitor(instagram_client, task_queue, poll_interval=12)
        instagram_monitor.start()

        global registration_bot
        from telegram_bot.registration_bot import RegistrationBot
        registration_bot = RegistrationBot()
        registration_bot.start()

        logger.info("Service running. Press Ctrl+C to terminate.")

        while True:
            time.sleep(1)

    except Exception as e:
        logger.critical(f"Fatal error during startup: {e}", exc_info=True)
        handle_shutdown(signal.SIGABRT, None)


if __name__ == "__main__":
    main()
