import time
import queue
import threading
from typing import Optional
from instagrapi import Client
from instagram.handler import process_message_event
from config import logger

_monitor_instance: Optional['InstagramMonitor'] = None

def get_instagram_monitor() -> Optional['InstagramMonitor']:
    """Returns the active InstagramMonitor singleton instance."""
    return _monitor_instance

def notify_registration_started() -> None:
    """
    Called when a user begins registration/linking on Telegram.
    Immediately triggers a fast poll and sets a fast polling cycle (4s)
    so the verification code is detected with zero delay.
    """
    if _monitor_instance:
        _monitor_instance.activate_fast_mode(duration=120)

class InstagramMonitor:
    def __init__(self, cl: Client, message_queue: queue.Queue, poll_interval: int = 12):
        """
        Monitors an Instagram account's inbox in a separate background thread.
        
        :param cl: Authenticated instagrapi Client.
        :param message_queue: Thread-safe queue to push new Reels details.
        :param poll_interval: Default sleep interval in seconds between polls.
        """
        global _monitor_instance
        _monitor_instance = self
        
        self.cl = cl
        self.queue = message_queue
        self.normal_poll_interval = poll_interval
        self.fast_poll_interval = 4  # 4 seconds during registration for snappy response
        self._fast_mode_until = 0.0
        
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread = None
        self._poll_count = 0

    def trigger_immediate_poll(self) -> None:
        """Immediately wakes up monitor without waiting for the sleep timer."""
        logger.info("Immediate Instagram poll triggered.")
        self._wake_event.set()

    def activate_fast_mode(self, duration: int = 120) -> None:
        """
        Activates fast polling mode (4s) for the next `duration` seconds
        and triggers an immediate poll.
        """
        logger.info(f"Fast polling mode activated for {duration} seconds.")
        self._fast_mode_until = time.time() + duration
        self._wake_event.set()

    def reset_to_normal_interval(self) -> None:
        """Resets the monitor to normal polling interval immediately."""
        logger.info("Resetting monitor to normal polling interval.")
        self._fast_mode_until = 0.0

    def start(self) -> None:
        """
        Spawns and starts the daemon monitoring thread.
        """
        self._thread = threading.Thread(target=self._run, name="InstagramMonitorThread")
        self._thread.daemon = True
        self._thread.start()
        logger.info("Instagram monitor thread spawned successfully.")

    def stop(self) -> None:
        """
        Stops the monitoring thread.
        """
        logger.info("Stopping Instagram monitoring...")
        self._stop_event.set()
        self._wake_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Instagram monitoring stopped.")

    def _run(self) -> None:
        """
        Internal worker loop polling messages at the specified interval.
        Uses wake_event so polling can be instantly triggered on user events.
        """
        while not self._stop_event.is_set():
            try:
                self._poll_inbox()
            except Exception as e:
                logger.error(f"Failed to poll Instagram inbox: {e}", exc_info=True)
            
            # Determine current interval (fast mode if active, else normal)
            current_interval = self.fast_poll_interval if time.time() < self._fast_mode_until else self.normal_poll_interval
            
            # Responsive sleep that can be interrupted immediately by trigger_immediate_poll()
            self._wake_event.wait(timeout=current_interval)
            self._wake_event.clear()

    def _approve_pending_requests(self) -> list:
        """
        Fetches pending DM requests (from non-followers), approves them,
        and returns the newly approved threads so they can be processed.
        """
        approved_threads = []
        try:
            # Fetch pending/message-request threads via Instagram's pending inbox endpoint
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
                    # Approve the message request so it moves to the main inbox
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
        """
        Fetches the recent threads from direct inbox and processes messages.
        Also checks and auto-approves any pending message requests periodically.
        """
        self._poll_count += 1
        
        # Step 1: Auto-approve pending message requests every 3rd poll or while in fast mode
        # to avoid excessive network overhead on every single tick
        if self._poll_count % 3 == 0 or time.time() < self._fast_mode_until:
            self._approve_pending_requests()

        # Step 2: Fetch main inbox threads (10 threads is optimal and fast)
        logger.debug("Fetching Instagram direct threads...")
        threads = self.cl.direct_threads(amount=10)
        logger.info(f"Fetched {len(threads)} thread(s) from inbox.")

        for thread in threads:
            if not thread.messages:
                continue
            
            # Find the other user's username in the thread
            sender_username = None
            if thread.users:
                sender_username = thread.users[0].username
            
            # Inspect the latest 10 messages of the thread.
            # Process in reverse (oldest first) so that chronological order is preserved.
            messages = thread.messages[:10]
            for msg in reversed(messages):
                # Try to get username for this specific message user_id
                msg_sender = sender_username
                if msg.user_id and thread.users:
                    for u in thread.users:
                        if str(u.pk) == str(msg.user_id):
                            msg_sender = u.username
                            break
                process_message_event(msg, self.queue, msg_sender)
