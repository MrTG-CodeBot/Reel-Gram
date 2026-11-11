"""
URL shortcode parsing and Base64 primary key conversion utilities.
"""

from typing import Optional
from downloader.validator import extract_reel_code


def get_shortcode_from_url(url: str) -> Optional[str]:
    """Extracts the unique shortcode from an Instagram media URL."""
    return extract_reel_code(url)


def get_media_pk_from_code(code: str) -> int:
    """Decodes a Base64 Instagram shortcode to its numeric primary key (PK)."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    pk = 0
    for char in code:
        pk = (pk * 64) + alphabet.index(char)
    return pk
