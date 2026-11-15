"""
MongoDB database connection provider.
Manages the global MongoClient instance and handles connection checks.
"""

from pymongo import MongoClient
from config import MONGODB_URI, MONGODB_DB_NAME, logger

_client = None


def get_db():
    """
    Retrieves or establishes the active MongoDB database connection.
    Uses connection pooling via the singleton MongoClient.
    """
    global _client
    if _client is None:
        try:
            logger.info(f"Connecting to MongoDB: {MONGODB_URI}")
            _client = MongoClient(MONGODB_URI)
            _client.admin.command("ping")
            logger.info("Connected to MongoDB successfully.")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    return _client[MONGODB_DB_NAME]
