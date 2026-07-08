from pymongo import MongoClient
from config import MONGODB_URI, MONGODB_DB_NAME, logger

_client = None

def get_db():
    """
    Returns the MongoDB Database instance.
    Uses connection pooling provided by MongoClient.
    """
    global _client
    if _client is None:
        try:
            logger.info(f"Connecting to MongoDB at {MONGODB_URI}...")
            _client = MongoClient(MONGODB_URI)
            # Trigger connection check
            _client.admin.command('ping')
            logger.info("Successfully connected to MongoDB.")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    return _client[MONGODB_DB_NAME]
