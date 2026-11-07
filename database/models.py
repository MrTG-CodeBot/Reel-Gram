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

def is_message_processed(message_id: str) -> bool:
    """
    Checks if an Instagram message ID already exists in the database.
    """
    try:
        db = get_db()
        doc = db.reels.find_one({"instagram_message_id": message_id}, projection={"_id": 1})
        return doc is not None
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
    If the status is completed and telegram_chat_id is provided, increments the user's reels_received counter.
    """
    try:
        db = get_db()
        update_doc = {
            "telegram_message_id": telegram_message_id,
            "download_status": status,
            "updated_at": datetime.datetime.utcnow()
        }
        if telegram_chat_id:
            update_doc["telegram_chat_id"] = telegram_chat_id

        db.reels.update_one(
            {"instagram_message_id": message_id},
            {"$set": update_doc}
        )

        if status == "completed" and telegram_chat_id:
            increment_user_reel_count(telegram_chat_id)

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

def create_pending_registration(instagram_username: str, telegram_chat_id: str) -> str:
    """
    Creates/updates a registration record in a pending (unverified) state and returns
    a new verification code. Codes expire in 10 minutes.
    """
    db = get_db()
    instagram_username = instagram_username.strip().lower()
    code = f"RG-{generate_verification_code()}"
    expiry = datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
    
    # We clean up any existing unverified mapping for this Telegram chat first,
    # or if this Instagram user already exists, update/overwrite it.
    db.user_registrations.delete_many({"telegram_chat_id": telegram_chat_id, "verified": False})
    
    db.user_registrations.update_one(
        {"instagram_username": instagram_username},
        {
            "$set": {
                "telegram_chat_id": telegram_chat_id,
                "verified": False,
                "verification_code": code,
                "code_expires_at": expiry,
                "registered_at": datetime.datetime.utcnow()
            }
        },
        upsert=True
    )
    logger.info(f"Created pending registration for IG={instagram_username} TG={telegram_chat_id} with Code={code}")
    return code

def verify_registration(instagram_username: str, code: str) -> bool:
    """
    Verifies the code sent from Instagram. If matches and not expired, sets verified=True.
    Returns True if successfully verified, False otherwise.
    """
    db = get_db()
    instagram_username = instagram_username.strip().lower()
    code = code.strip().upper()
    
    doc = db.user_registrations.find_one({"instagram_username": instagram_username})
    if not doc:
        logger.warning(f"No registration document found for Instagram user: {instagram_username}")
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
            {"instagram_username": instagram_username},
            {
                "$set": {
                    "verified": True,
                    "verification_code": None,
                    "code_expires_at": None,
                    "verified_at": datetime.datetime.utcnow()
                }
            }
        )
        tg_chat_id = doc.get("telegram_chat_id")
        if tg_chat_id:
            db.bot_users.update_one(
                {"telegram_chat_id": tg_chat_id},
                {
                    "$set": {
                        "linked_instagram": instagram_username,
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
        instagram_username = instagram_username.strip().lower()
        doc = db.user_registrations.find_one({"instagram_username": instagram_username, "verified": True})
        if doc:
            return doc["telegram_chat_id"]
    except Exception as e:
        logger.error(f"Error getting TG chat for IG={instagram_username}: {e}")
    return None

def get_registration_by_telegram(telegram_chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Gets the registration mapping for a Telegram chat if any exists.
    """
    try:
        db = get_db()
        doc = db.user_registrations.find_one({"telegram_chat_id": telegram_chat_id})
        return doc
    except Exception as e:
        logger.error(f"Error getting registration by TG={telegram_chat_id}: {e}")
    return None

def unlink_user_by_telegram(telegram_chat_id: str) -> bool:
    """
    Removes any registration (verified or pending) associated with the Telegram chat.
    Returns True if a document was deleted.
    """
    try:
        db = get_db()
        result = db.user_registrations.delete_many({"telegram_chat_id": telegram_chat_id})
        db.bot_users.update_one(
            {"telegram_chat_id": telegram_chat_id},
            {"$unset": {"linked_instagram": ""}}
        )
        return result.deleted_count > 0
    except Exception as e:
        logger.error(f"Error unlinking TG chat {telegram_chat_id}: {e}")
        return False

# --- Bot User Tracking (for /start, broadcast, stats) ---

def increment_user_reel_count(telegram_chat_id: str) -> None:
    """
    Increments the count of reels delivered to a specific user chat
    and updates their last active timestamp.
    """
    try:
        db = get_db()
        db.bot_users.update_one(
            {"telegram_chat_id": telegram_chat_id},
            {
                "$inc": {"reels_received": 1},
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
        connected_users = db.user_registrations.count_documents({"verified": True})
        pending_users = db.user_registrations.count_documents({"verified": False})
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

