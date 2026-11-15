"""
Background worker that polls the Instagram Direct Message inbox for new messages,
auto-approves pending message requests, and dispatches tasks to the worker queue.
"""

import time
import queue
import threading
import datetime
from typing import Optional
from instagrapi import Client
from instagram.handler import process_message_event
from database.models import insert_reel
from config import logger

_monitor_instance: Optional["InstagramMonitor"] = None


def get_instagram_monitor() -> Optional["InstagramMonitor"]:
    """Returns the active InstagramMonitor singleton instance."""
    return _monitor_instance


def notify_registration_started() -> None:
    """
    Temporarily switches monitor to fast polling mode (4s) when a user initiates
    registration on Telegram, ensuring rapid code detection.
    """
    if _monitor_instance:
        _monitor_instance.activate_fast_mode(duration=120)


class InstagramMonitor:
    """
    Asynchronous poller for Instagram Direct Messages.
    Supports dynamic polling speeds and thread-safe wake triggers.
    """

    def __init__(self, cl: Client, message_queue: queue.Queue, poll_interval: int = 12):
        global _monitor_instance
        _monitor_instance = self

        self.cl = cl
        self.queue = message_queue
        self.normal_poll_interval = poll_interval
        self.fast_poll_interval = 4
        self._fast_mode_until = 0.0

        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread = None
        self._poll_count = 0

    def trigger_immediate_poll(self) -> None:
        """Interrupts current wait interval to poll the inbox immediately."""
        logger.info("Immediate Instagram poll triggered.")
        self._wake_event.set()

    def activate_fast_mode(self, duration: int = 120) -> None:
        """Enables accelerated polling for a specified duration in seconds."""
        logger.info(f"Fast polling mode activated for {duration} seconds.")
        self._fast_mode_until = time.time() + duration
        self._wake_event.set()

    def reset_to_normal_interval(self) -> None:
        """Reverts the monitor back to normal polling cadence."""
        logger.info("Resetting monitor to normal polling interval.")
        self._fast_mode_until = 0.0

    def start(self) -> None:
        """Starts the background monitoring thread."""
        self._thread = threading.Thread(target=self._run, name="InstagramMonitorThread")
        self._thread.daemon = True
        self._thread.start()
        logger.info("Instagram monitor thread started.")

    def stop(self) -> None:
        """Signals the background monitoring thread to stop and waits for exit."""
        logger.info("Stopping Instagram monitoring...")
        self._stop_event.set()
        self._wake_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Instagram monitoring stopped.")

    def _run(self) -> None:
        """Worker loop executing poll operations at configured intervals."""
        while not self._stop_event.is_set():
            try:
                self._poll_inbox()
            except Exception as e:
                logger.error(f"Failed to poll Instagram inbox: {e}", exc_info=True)

            current_interval = (
                self.fast_poll_interval
                if time.time() < self._fast_mode_until
                else self.normal_poll_interval
            )

            self._wake_event.wait(timeout=current_interval)
            self._wake_event.clear()

    def _approve_pending_requests(self) -> list:
        """
        Retrieves and auto-approves pending message requests from non-followers.
        """
        approved_threads = []
        try:
            result = self.cl.private_request(
                "direct_v2/pending_inbox/",
                params={"visual_message_return_type": "unseen", "limit": "20"}
            )
            pending_threads_data = result.get("inbox", {}).get("threads", [])
            if not pending_threads_data:
                return approved_threads

            logger.info(f"Found {len(pending_threads_data)} pending DM request(s). Approving...")
            for thread_data in pending_threads_data:
                thread_id = thread_data.get("thread_id") or thread_data.get("thread_v2_id")
                if not thread_id:
                    continue
                try:
                    self.cl.private_request(
                        f"direct_v2/threads/{thread_id}/approve/",
                        data=self.cl.with_action_data({})
                    )
                    logger.info(f"Approved DM request for thread: {thread_id}")
                except Exception as e:
                    logger.warning(f"Failed to approve thread {thread_id}: {e}")
        except Exception as e:
            logger.warning(f"Could not fetch pending inbox: {e}")
        return approved_threads

    def _poll_inbox(self) -> None:
        """Fetches active threads and forwards new messages for evaluation."""
        self._poll_count += 1

        # Check pending requests every 3rd poll or when in fast registration mode
        if self._poll_count % 3 == 0 or time.time() < self._fast_mode_until:
            self._approve_pending_requests()

        threads = self.cl.direct_threads(amount=10)
        logger.info(f"Fetched {len(threads)} thread(s) from inbox.")

        for thread in threads:
            if not thread.messages:
                continue

            sender_username = thread.users[0].username if thread.users else None
            messages = thread.messages[:10]

            for msg in reversed(messages):
                # Skip self messages
                if str(msg.user_id) == str(self.cl.user_id) or getattr(msg, "is_sent_by_viewer", False):
                    continue

                # Ignore messages older than 2 hours to avoid processing old history on restart
                if getattr(msg, "timestamp", None):
                    try:
                        msg_time = msg.timestamp
                        if hasattr(msg_time, "tzinfo") and msg_time.tzinfo is not None:
                            now_dt = datetime.datetime.now(datetime.timezone.utc)
                        else:
                            now_dt = datetime.datetime.utcnow()
                        if (now_dt - msg_time).total_seconds() > 2 * 3600:
                            insert_reel(msg.id, "N/A", "ignored_too_old", sender_username)
                            continue
                    except Exception:
                        pass

                msg_sender = sender_username
                if msg.user_id and thread.users:
                    for u in thread.users:
                        if str(u.pk) == str(msg.user_id):
                            msg_sender = u.username
                            break

                process_message_event(msg, self.queue, msg_sender, cl=self.cl, thread_id=thread.id)
