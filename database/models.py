import datetime
import random
import string
from typing import Optional, List, Dict, Any
from database.db import get_db
from config import logger

def init_db() -> None:
    """
    Initializes database indexes in MongoDB.
    """
    try:
        db = get_db()
        # Indexes for reels
        db.reels.create_index("instagram_message_id", unique=True)
        db.reels.create_index("instagram_url")
        
        # Indexes for user registrations
        db.user_registrations.create_index("instagram_username", unique=True)
        db.user_registrations.create_index("telegram_chat_id")
        
        logger.info("MongoDB indexes initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing MongoDB: {e}")
        raise

# In-memory cache of evaluated Instagram message IDs to avoid hundreds of sequential DB calls
_PROCESSED_MESSAGES_CACHE = set()

def is_message_processed(message_id: str) -> bool:
    """
    Checks if an Instagram message ID already exists in the database.
    Uses an in-memory cache for instant O(1) lookups during polling.
    """
    if message_id in _PROCESSED_MESSAGES_CACHE:
        return True
    try:
        db = get_db()
        doc = db.reels.find_one({"instagram_message_id": message_id}, projection={"_id": 1})
        if doc is not None:
            if len(_PROCESSED_MESSAGES_CACHE) > 10000:
                _PROCESSED_MESSAGES_CACHE.clear()
            _PROCESSED_MESSAGES_CACHE.add(message_id)
            return True
        return False
    except Exception as e:
        logger.error(f"Error checking message: {e}")
        return False

def is_url_processed(url: str) -> bool:
    """
    Checks if a Reel URL has already been processed.
    """
    try:
        db = get_db()
        doc = db.reels.find_one({"instagram_url": url}, projection={"_id": 1})
        return doc is not None
    except Exception as e:
        logger.error(f"Error checking url: {e}")
        return False

def insert_reel(message_id: str, url: str, status: str = "pending", sender_username: Optional[str] = None) -> None:
    """
    Inserts a new tracking record for a received Reel message.
    """
    try:
        _PROCESSED_MESSAGES_CACHE.add(message_id)
        db = get_db()
        db.reels.update_one(
            {"instagram_message_id": message_id},
            {
                "$set": {
                    "instagram_url": url,
                    "download_status": status,
                    "sender_username": sender_username,
                    "created_at": datetime.datetime.utcnow()
                }
            },
            upsert=True
        )
        logger.info(f"Inserted/updated reel record: MSG_ID={message_id}, URL={url}, STATUS={status}, SENDER={sender_username}")
    except Exception as e:
        logger.error(f"Error inserting reel: {e}")
        raise

def update_reel_status(message_id: str, telegram_message_id: str = None, status: str = "completed", telegram_chat_id: str = None) -> None:
    """
    Updates the telegram upload status, resulting telegram message ID, and target chat ID for a Reel.
    If telegram_chat_id is provided, increments the user's completed or failed reel counter.
    """
    try:
        db = get_db()
        update_doc = {
            "telegram_message_id": telegram_message_id,
            "download_status": status,
            "updated_at": datetime.datetime.utcnow()
        }
        if telegram_chat_id:
            update_doc["telegram_chat_id"] = str(telegram_chat_id)

        db.reels.update_one(
            {"instagram_message_id": message_id},
            {"$set": update_doc}
        )

        if telegram_chat_id:
            if status == "completed":
                increment_user_reel_count(telegram_chat_id, success=True)
            elif status in ["failed", "download_failed"]:
                increment_user_reel_count(telegram_chat_id, success=False)

        logger.info(f"Updated reel record: MSG_ID={message_id}, TG_MSG_ID={telegram_message_id}, STATUS={status}")
    except Exception as e:
        logger.error(f"Error updating reel: {e}")
        raise

def get_pending_reels() -> list:
    """
    Fetches all Reel records from the database that are in a non-terminal state.
    """
    try:
        db = get_db()
        cursor = db.reels.find({"download_status": {"$in": ["pending", "downloading", "uploading"]}})
        return [{"message_id": doc["instagram_message_id"], "url": doc["instagram_url"], "sender_username": doc.get("sender_username")} for doc in cursor]
    except Exception as e:
        logger.error(f"Error getting pending reels: {e}")
        return []

# --- Multi-User Verification / Registration ---

def generate_verification_code() -> str:
    """Generates a 6-digit numeric verification code."""
    return "".join(random.choices(string.digits, k=6))

def create_pending_registration(instagram_username: str, telegram_chat_id: str) -> tuple[Optional[str], str]:
    """
    Creates/updates a registration record in a pending (unverified) state.
    Enforces Option 1:
      - Max 2 verified accounts per Telegram user.
      - Exclusive Lock: Cannot register an Instagram username that is already verified by another Telegram user.
    Returns: (code, status)
      status can be:
        - "ok": code generated successfully
        - "already_linked_to_you": this exact username is already verified to this chat
        - "already_linked_by_other": this exact username is already verified to another chat
        - "limit_reached": this Telegram chat already has 2 verified accounts
    """
    db = get_db()
    instagram_username = instagram_username.strip().lower().replace("@", "").strip(".")
    telegram_chat_id = str(telegram_chat_id)
    
    # 1. Check how many verified accounts this Telegram chat already has
    my_verified = list(db.user_registrations.find({"telegram_chat_id": telegram_chat_id, "verified": True}))
    my_verified_names = [d.get("instagram_username", "").lower() for d in my_verified]
    
    if instagram_username in my_verified_names:
        return None, "already_linked_to_you"
        
    if len(my_verified) >= 2:
        return None, "limit_reached"

    # 2. Check if this Instagram username is already registered anywhere
    existing = db.user_registrations.find_one({"instagram_username": instagram_username})
    if not existing:
        existing = db.user_registrations.find_one({"instagram_username": f"{instagram_username}."})

    if existing:
        if existing.get("verified"):
            if str(existing.get("telegram_chat_id")) == telegram_chat_id:
                return None, "already_linked_to_you"
            else:
                # Option 1: Exclusive lock!
                return None, "already_linked_by_other"
        else:
            # Existing record is unverified/pending. Remove it so current user can claim it
            db.user_registrations.delete_one({"_id": existing["_id"]})

    # 3. Clean up any previous UNVERIFIED registrations for this Telegram chat
    db.user_registrations.delete_many({"telegram_chat_id": telegram_chat_id, "verified": False})

    # 4. Insert new pending registration
    code = f"RG-{generate_verification_code()}"
    expiry = datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
    
    db.user_registrations.insert_one({
        "instagram_username": instagram_username,
        "telegram_chat_id": telegram_chat_id,
        "verified": False,
        "verification_code": code,
        "code_expires_at": expiry,
        "registered_at": datetime.datetime.utcnow()
    })
    logger.info(f"Created pending registration for IG={instagram_username} TG={telegram_chat_id} with Code={code}")
    return code, "ok"

def verify_registration(instagram_username: str, code: str) -> bool:
    """
    Verifies the code sent from Instagram. If matches and not expired, sets verified=True.
    Matches either by exact username, username without trailing dot, or by verification_code.
    Returns True if successfully verified, False otherwise.
    """
    db = get_db()
    instagram_username = instagram_username.strip().lower().replace("@", "").strip(".")
    code = code.strip().upper()
    
    # 1. Search by cleaned username
    doc = db.user_registrations.find_one({"instagram_username": instagram_username})
    if not doc:
        # Check if username in DB was stored with a trailing period
        doc = db.user_registrations.find_one({"instagram_username": f"{instagram_username}."})

    # 2. If not found, lookup by the unique verification code
    if not doc and code:
        doc = db.user_registrations.find_one({"verification_code": code})
        if doc:
            logger.info(
                f"Matched registration by code '{code}' for Instagram user: '{instagram_username}' "
                f"(registered in DB as '{doc.get('instagram_username')}')"
            )

    if not doc:
        logger.warning(f"No registration document found for Instagram user: {instagram_username} (code: {code})")
        return False
        
    if doc.get("verified"):
        logger.info(f"Instagram user {instagram_username} is already verified.")
        return True
        
    expiry = doc.get("code_expires_at")
    if expiry and datetime.datetime.utcnow() > expiry:
        logger.warning(f"Verification code for {instagram_username} has expired.")
        return False
        
    if doc.get("verification_code") == code:
        db.user_registrations.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "instagram_username": instagram_username,
                    "verified": True,
                    "verification_code": None,
                    "code_expires_at": None,
                    "verified_at": datetime.datetime.utcnow()
                }
            }
        )
        tg_chat_id = doc.get("telegram_chat_id")
        if tg_chat_id:
            # Sync all verified accounts into bot_users for tracking & stats
            verified_docs = list(db.user_registrations.find({"telegram_chat_id": str(tg_chat_id), "verified": True}))
            accounts = [d.get("instagram_username") for d in verified_docs if d.get("instagram_username")]
            linked_display = ", @".join(accounts)
            db.bot_users.update_one(
                {"telegram_chat_id": str(tg_chat_id)},
                {
                    "$set": {
                        "linked_instagram": f"@{linked_display}" if accounts else None,
                        "linked_accounts": accounts,
                        "last_seen": datetime.datetime.utcnow()
                    }
                }
            )
        logger.info(f"Successfully verified registration for Instagram user: {instagram_username}")
        return True
        
    logger.warning(f"Verification code mismatch for {instagram_username}: expected {doc.get('verification_code')}, got {code}")
    return False

def get_telegram_chat_for_user(instagram_username: str) -> Optional[str]:
    """
    Returns the telegram_chat_id for the given Instagram username if verified.
    """
    try:
        db = get_db()
        clean = instagram_username.strip().lower().replace("@", "").strip(".")
        doc = db.user_registrations.find_one({"instagram_username": clean, "verified": True})
        if not doc:
            doc = db.user_registrations.find_one({"instagram_username": f"{clean}.", "verified": True})
        if doc:
            return doc["telegram_chat_id"]
    except Exception as e:
        logger.error(f"Error getting TG chat for IG={instagram_username}: {e}")
    return None

def get_registrations_by_telegram(telegram_chat_id: str) -> List[Dict[str, Any]]:
    """
    Gets all registration mappings (verified & pending) for a Telegram chat.
    """
    try:
        db = get_db()
        return list(db.user_registrations.find({"telegram_chat_id": str(telegram_chat_id)}))
    except Exception as e:
        logger.error(f"Error getting registrations for TG={telegram_chat_id}: {e}")
        return []

def get_verified_registrations(telegram_chat_id: str) -> List[Dict[str, Any]]:
    """
    Gets only verified registration mappings for a Telegram chat.
    """
    try:
        db = get_db()
        return list(db.user_registrations.find({"telegram_chat_id": str(telegram_chat_id), "verified": True}))
    except Exception as e:
        logger.error(f"Error getting verified registrations for TG={telegram_chat_id}: {e}")
        return []

def get_registration_by_telegram(telegram_chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Gets the first registration mapping for a Telegram chat (backwards compatibility).
    """
    regs = get_registrations_by_telegram(telegram_chat_id)
    return regs[0] if regs else None

def get_registration_by_instagram(instagram_username: str) -> Optional[Dict[str, Any]]:
    """
    Gets the registration mapping for an Instagram username (verified or pending).
    """
    try:
        db = get_db()
        clean = instagram_username.strip().lower().replace("@", "").strip(".")
        doc = db.user_registrations.find_one({"instagram_username": clean})
        if not doc:
            doc = db.user_registrations.find_one({"instagram_username": f"{clean}."})
        return doc
    except Exception as e:
        logger.error(f"Error getting registration by IG={instagram_username}: {e}")
    return None

def unlink_user_by_telegram(telegram_chat_id: str, instagram_username: Optional[str] = None) -> bool:
    """
    Removes registrations for the Telegram chat.
    If instagram_username is specified, unlinks only that account.
    If None, unlinks all accounts for this Telegram chat.
    """
    try:
        db = get_db()
        query = {"telegram_chat_id": str(telegram_chat_id)}
        if instagram_username:
            clean = instagram_username.strip().lower().replace("@", "").strip(".")
            query["instagram_username"] = clean

        result = db.user_registrations.delete_many(query)
        
        # Resync bot_users
        verified_docs = list(db.user_registrations.find({"telegram_chat_id": str(telegram_chat_id), "verified": True}))
        accounts = [d.get("instagram_username") for d in verified_docs if d.get("instagram_username")]
        
        if accounts:
            db.bot_users.update_one(
                {"telegram_chat_id": str(telegram_chat_id)},
                {
                    "$set": {
                        "linked_instagram": f"@{', @'.join(accounts)}",
                        "linked_accounts": accounts
                    }
                }
            )
        else:
            db.bot_users.update_one(
                {"telegram_chat_id": str(telegram_chat_id)},
                {
                    "$unset": {
                        "linked_instagram": "",
                        "linked_accounts": ""
                    }
                }
            )
        return result.deleted_count > 0
    except Exception as e:
        logger.error(f"Error unlinking TG chat {telegram_chat_id}: {e}")
        return False

# --- Bot User Tracking (for /start, broadcast, stats) ---

def increment_user_reel_count(telegram_chat_id: str, success: bool = True) -> None:
    """
    Increments the count of completed or failed reels for a specific user chat
    and updates their last active timestamp.
    """
    try:
        db = get_db()
        field = "reels_received" if success else "reels_failed"
        db.bot_users.update_one(
            {"telegram_chat_id": str(telegram_chat_id)},
            {
                "$inc": {field: 1},
                "$set": {
                    "last_active_at": datetime.datetime.utcnow(),
                    "last_seen": datetime.datetime.utcnow()
                }
            },
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error incrementing user reel count TG={telegram_chat_id}: {e}")

def track_user(telegram_chat_id: str, first_name: str = None, username: str = None) -> bool:
    """
    Tracks a bot user in the bot_users collection.
    Returns True if the user is NEW (first time seen), False if already existed.
    """
    try:
        db = get_db()
        existing = db.bot_users.find_one({"telegram_chat_id": telegram_chat_id})
        
        # Check if user already has an active verified registration
        linked_reg = db.user_registrations.find_one({"telegram_chat_id": telegram_chat_id, "verified": True})
        linked_ig = linked_reg["instagram_username"] if linked_reg else (existing.get("linked_instagram") if existing else None)

        update_set = {
            "first_name": first_name,
            "username": username,
            "last_seen": datetime.datetime.utcnow()
        }
        if linked_ig:
            update_set["linked_instagram"] = linked_ig

        db.bot_users.update_one(
            {"telegram_chat_id": telegram_chat_id},
            {
                "$set": update_set,
                "$setOnInsert": {
                    "joined_at": datetime.datetime.utcnow(),
                    "reels_received": 0
                }
            },
            upsert=True
        )
        return existing is None
    except Exception as e:
        logger.error(f"Error tracking user TG={telegram_chat_id}: {e}")
        return False

def get_all_user_chat_ids() -> List[str]:
    """
    Returns a list of all tracked user chat IDs for broadcast.
    """
    try:
        db = get_db()
        docs = db.bot_users.find({}, {"telegram_chat_id": 1})
        return [doc["telegram_chat_id"] for doc in docs]
    except Exception as e:
        logger.error(f"Error getting all user chat IDs: {e}")
        return []

def get_user_count() -> int:
    """
    Returns the total number of tracked bot users.
    """
    try:
        db = get_db()
        return db.bot_users.count_documents({})
    except Exception as e:
        logger.error(f"Error getting user count: {e}")
        return 0

def get_db_stats() -> Dict[str, Any]:
    """
    Returns MongoDB database stats including dataSize, storageSize, and freeStorageSize.
    """
    try:
        db = get_db()
        stats = db.command("dbStats")
        return {
            "dataSize": stats.get("dataSize", 0),
            "storageSize": stats.get("storageSize", 0),
            "freeStorageSize": stats.get("freeStorageSize", 0),
            "collections": stats.get("collections", 0),
            "objects": stats.get("objects", 0)
        }
    except Exception as e:
        logger.error(f"Error getting DB stats: {e}")
        return {}

def get_bot_owner_stats() -> Dict[str, Any]:
    """
    Calculates detailed metrics for the bot owner:
    - User base (total, new 24h, active 24h, active 7d)
    - Instagram linking (connected, pending, connection rate)
    - Feature usage (users receiving reels, unique IG senders, reels processed/completed/failed)
    - DB storage metrics
    """
    try:
        db = get_db()
        now = datetime.datetime.utcnow()
        day_ago = now - datetime.timedelta(days=1)
        week_ago = now - datetime.timedelta(days=7)

        # User counts
        total_users = db.bot_users.count_documents({})
        new_users_24h = db.bot_users.count_documents({"joined_at": {"$gte": day_ago}})
        new_users_7d = db.bot_users.count_documents({"joined_at": {"$gte": week_ago}})
        active_users_24h = db.bot_users.count_documents({"last_seen": {"$gte": day_ago}})
        active_users_7d = db.bot_users.count_documents({"last_seen": {"$gte": week_ago}})

        # Instagram connection counts
        connected_users = len(db.user_registrations.distinct("telegram_chat_id", {"verified": True}))
        pending_users = len(db.user_registrations.distinct("telegram_chat_id", {"verified": False}))
        connection_rate = round((connected_users / total_users * 100), 1) if total_users > 0 else 0.0

        # Feature usage counts
        feature_users = db.bot_users.count_documents({"reels_received": {"$gt": 0}})
        unique_ig_senders = len(db.reels.distinct("sender_username", {"sender_username": {"$nin": [None, ""]}}))

        # Reel counts (excluding verification messages or non-reels)
        total_reels = db.reels.count_documents({"instagram_url": {"$regex": r"instagram\.com"}})
        if total_reels == 0:
            total_reels = db.reels.count_documents({"instagram_url": {"$ne": "N/A"}})

        completed_reels = db.reels.count_documents({"download_status": "completed"})
        failed_reels = db.reels.count_documents({"download_status": {"$in": ["failed", "download_failed"]}})
        in_flight_reels = db.reels.count_documents({"download_status": {"$in": ["pending", "downloading", "uploading"]}})

        success_rate = round((completed_reels / total_reels * 100), 1) if total_reels > 0 else 0.0

        db_stats = get_db_stats()

        return {
            "total_users": total_users,
            "new_users_24h": new_users_24h,
            "new_users_7d": new_users_7d,
            "active_users_24h": active_users_24h,
            "active_users_7d": active_users_7d,
            "connected_users": connected_users,
            "pending_users": pending_users,
            "connection_rate": connection_rate,
            "feature_users": feature_users,
            "unique_ig_senders": unique_ig_senders,
            "total_reels": total_reels,
            "completed_reels": completed_reels,
            "failed_reels": failed_reels,
            "in_flight_reels": in_flight_reels,
            "success_rate": success_rate,
            "db_stats": db_stats,
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        logger.error(f"Error compiling bot owner stats: {e}")
        return {}

def get_recent_users(limit: int = 10) -> List[Dict[str, Any]]:
    """Returns the most recent active bot users and their activity stats."""
    try:
        db = get_db()
        users = list(db.bot_users.find({}).sort("last_seen", -1).limit(limit))
        return users
    except Exception as e:
        logger.error(f"Error fetching recent users: {e}")
        return []

def get_user_reel_stats(telegram_chat_id: str, linked_accounts: Optional[List[str]] = None) -> tuple[int, int]:
    """
    Returns (completed_count, failed_count) for a specific Telegram chat ID.
    Merges bot_users tracking counters with reels collection records.
    """
    try:
        db = get_db()
        chat_id_str = str(telegram_chat_id)
        user_doc = db.bot_users.find_one({"telegram_chat_id": chat_id_str}) or {}
        completed = int(user_doc.get("reels_received", 0) or 0)
        failed = int(user_doc.get("reels_failed", 0) or 0)

        filter_or: List[Dict[str, Any]] = [{"telegram_chat_id": chat_id_str}]
        if linked_accounts:
            clean_accs = [a.replace("@", "").strip().lower() for a in linked_accounts if a]
            if clean_accs:
                filter_or.append({"sender_username": {"$in": clean_accs}})

        db_failed = db.reels.count_documents({
            "$or": filter_or,
            "download_status": {"$in": ["failed", "download_failed"]}
        })
        db_completed = db.reels.count_documents({
            "$or": filter_or,
            "download_status": "completed"
        })

        return max(completed, db_completed), max(failed, db_failed)
    except Exception as e:
        logger.error(f"Error getting reel stats for TG={telegram_chat_id}: {e}")
        return 0, 0

def get_all_users_detailed() -> List[Dict[str, Any]]:
    """
    Fetches all registered bot users, ordered by joined_at.
    Returns complete user metadata, linked Instagram accounts, and completed/failed reel counts.
    """
    try:
        db = get_db()
        users = list(db.bot_users.find({}).sort("joined_at", 1))
        result = []
        for u in users:
            chat_id = str(u.get("telegram_chat_id", ""))
            if not chat_id:
                continue

            # Fetch linked accounts from user_registrations for real-time accuracy
            verified_regs = list(db.user_registrations.find({"telegram_chat_id": chat_id, "verified": True}))
            accounts = [r.get("instagram_username") for r in verified_regs if r.get("instagram_username")]
            if not accounts and u.get("linked_instagram"):
                accounts = [a.replace("@", "").strip() for a in str(u.get("linked_instagram")).split(",") if a.strip()]

            completed, failed = get_user_reel_stats(chat_id, linked_accounts=accounts)

            result.append({
                "telegram_chat_id": chat_id,
                "first_name": u.get("first_name") or "Anonymous",
                "username": u.get("username"),
                "linked_accounts": accounts,
                "completed_count": completed,
                "failed_count": failed,
                "joined_at": u.get("joined_at"),
                "last_seen": u.get("last_seen")
            })
        return result
    except Exception as e:
        logger.error(f"Error fetching detailed users: {e}")
        return []

