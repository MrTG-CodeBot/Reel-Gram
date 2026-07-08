from typing import Optional
from downloader.validator import extract_reel_code

def get_shortcode_from_url(url: str) -> Optional[str]:
    """
    Parses an Instagram Reel URL and returns its unique shortcode.
    """
    return extract_reel_code(url)

def get_media_pk_from_code(code: str) -> int:
    """
    Converts an Instagram shortcode back to its primary key (PK) representation.
    """
    # Alphabet translation for Base64-like shortcodes to integer PK
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
    pk = 0
    for char in code:
        pk = (pk * 64) + alphabet.index(char)
    return pk
