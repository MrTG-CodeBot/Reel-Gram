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

def update_reel_status(message_id: str, telegram_message_id: str = None, status: str = "completed") -> None:
    """
    Updates the telegram upload status and the resulting telegram message ID for a Reel.
    """
    try:
        db = get_db()
        db.reels.update_one(
            {"instagram_message_id": message_id},
            {
                "$set": {
                    "telegram_message_id": telegram_message_id,
                    "download_status": status,
                    "updated_at": datetime.datetime.utcnow()
                }
            }
        )
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
        return result.deleted_count > 0
    except Exception as e:
        logger.error(f"Error unlinking TG chat {telegram_chat_id}: {e}")
        return False

# --- Bot User Tracking (for /start, broadcast, stats) ---

def track_user(telegram_chat_id: str, first_name: str = None, username: str = None) -> bool:
    """
    Tracks a bot user in the bot_users collection.
    Returns True if the user is NEW (first time seen), False if already existed.
    """
    try:
        db = get_db()
        existing = db.bot_users.find_one({"telegram_chat_id": telegram_chat_id})
        db.bot_users.update_one(
            {"telegram_chat_id": telegram_chat_id},
            {
                "$set": {
                    "first_name": first_name,
                    "username": username,
                    "last_seen": datetime.datetime.utcnow()
                },
                "$setOnInsert": {
                    "joined_at": datetime.datetime.utcnow()
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

