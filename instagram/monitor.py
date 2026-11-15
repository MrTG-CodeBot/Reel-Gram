import time
import queue
import threading
from instagrapi import Client
from instagram.handler import process_message_event
from config import logger

class InstagramMonitor:
    def __init__(self, cl: Client, message_queue: queue.Queue, poll_interval: int = 30):
        """
        Monitors an Instagram account's inbox in a separate background thread.
        
        :param cl: Authenticated instagrapi Client.
        :param message_queue: Thread-safe queue to push new Reels details.
        :param poll_interval: Sleep interval in seconds between polls.
        """
        self.cl = cl
        self.queue = message_queue
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread = None

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
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Instagram monitoring stopped.")

    def _run(self) -> None:
        """
        Internal worker loop polling messages at the specified interval.
        """
        while not self._stop_event.is_set():
            try:
                self._poll_inbox()
            except Exception as e:
                logger.error(f"Failed to poll Instagram inbox: {e}", exc_info=True)
            
            # Efficient polling sleep that checks for shutdown signals every 1 second
            for _ in range(self.poll_interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

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
        Also checks and auto-approves any pending message requests.
        """
        # Step 1: Auto-approve pending message requests so they appear in main inbox
        self._approve_pending_requests()

        # Step 2: Fetch main inbox threads
        logger.debug("Fetching Instagram direct threads...")
        threads = self.cl.direct_threads(amount=20)
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
