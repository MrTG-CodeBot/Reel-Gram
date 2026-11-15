import re
from typing import Optional
from config import logger

# Regex patterns to capture the shortcode group (1)
REEL_PATTERNS = [
    re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/reel/([A-Za-z0-9_\-]+)", re.IGNORECASE),
    re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/share/reel/([A-Za-z0-9_\-]+)", re.IGNORECASE),
]

def extract_reel_code(url: str) -> Optional[str]:
    """
    Extracts the Reel shortcode from the given Instagram URL if it fits supported patterns.
    Returns None if the URL does not represent a supported Reel.
    """
    if not url:
        return None
    for pattern in REEL_PATTERNS:
        match = pattern.search(url)
        if match:
            code = match.group(1)
            logger.debug(f"Extracted shortcode '{code}' from URL: {url}")
            return code
    logger.debug(f"Failed to extract Reel shortcode from URL: {url}")
    return None

def normalize_reel_url(url: str) -> Optional[str]:
    """
    Validates the URL format, removes tracking/query parameters, and returns
    a standardized canonical Reel URL: https://www.instagram.com/reel/{shortcode}/
    Returns None if URL is invalid.
    """
    code = extract_reel_code(url)
    if code:
        return f"https://www.instagram.com/reel/{code}/"
    return None

def is_valid_reel_url(url: str) -> bool:
    """
    Checks if a URL is a valid, supported Instagram Reel link.
    """
    valid = extract_reel_code(url) is not None
    logger.debug(f"URL validation check: URL={url}, Valid={valid}")
    return valid
