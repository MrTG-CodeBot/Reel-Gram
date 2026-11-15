import re
from typing import Optional, Tuple
from config import logger

# Regex patterns to capture the shortcode or ID
REEL_PATTERNS = [
    re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/reel/([A-Za-z0-9_\-]+)", re.IGNORECASE),
    re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/share/reel/([A-Za-z0-9_\-]+)", re.IGNORECASE),
]

POST_PATTERNS = [
    re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/p/([A-Za-z0-9_\-]+)", re.IGNORECASE),
    re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/share/p/([A-Za-z0-9_\-]+)", re.IGNORECASE),
]

STORY_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/stories/([A-Za-z0-9_.\-]+)/([0-9]+)",
    re.IGNORECASE
)

HIGHLIGHT_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/stories/highlights/([0-9A-Za-z_\-]+)",
    re.IGNORECASE
)

def detect_media_type(url: str) -> Optional[str]:
    """
    Detects the media type from the given Instagram URL.
    Returns: 'reel', 'post', 'story', 'highlight', or None.
    """
    if not url:
        return None
    for pattern in REEL_PATTERNS:
        if pattern.search(url):
            return "reel"
    for pattern in POST_PATTERNS:
        if pattern.search(url):
            return "post"
    if HIGHLIGHT_PATTERN.search(url):
        return "highlight"
    if STORY_PATTERN.search(url):
        return "story"
    return None

def extract_media_code(url: str) -> Optional[str]:
    """
    Extracts the shortcode or media identifier from any supported Instagram URL.
    """
    if not url:
        return None
    for pattern in REEL_PATTERNS + POST_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    
    h_match = HIGHLIGHT_PATTERN.search(url)
    if h_match:
        return h_match.group(1)
        
    s_match = STORY_PATTERN.search(url)
    if s_match:
        return s_match.group(2) # story ID
        
    return None

def normalize_instagram_url(url: str) -> Optional[str]:
    """
    Validates the URL format, removes tracking/query parameters, and returns
    a standardized canonical Instagram URL for Reels, Posts, Stories, or Highlights.
    """
    if not url:
        return None
        
    # 1. Reels
    for pattern in REEL_PATTERNS:
        m = pattern.search(url)
        if m:
            return f"https://www.instagram.com/reel/{m.group(1)}/"
            
    # 2. Posts (single photo/video or carousel)
    for pattern in POST_PATTERNS:
        m = pattern.search(url)
        if m:
            return f"https://www.instagram.com/p/{m.group(1)}/"
            
    # 3. Highlights
    h_m = HIGHLIGHT_PATTERN.search(url)
    if h_m:
        return f"https://www.instagram.com/stories/highlights/{h_m.group(1)}/"
        
    # 4. Stories
    s_m = STORY_PATTERN.search(url)
    if s_m:
        username = s_m.group(1)
        story_id = s_m.group(2)
        return f"https://www.instagram.com/stories/{username}/{story_id}/"
        
    return None

# Backwards compatibility wrappers
def extract_reel_code(url: str) -> Optional[str]:
    return extract_media_code(url)

def normalize_reel_url(url: str) -> Optional[str]:
    return normalize_instagram_url(url)

def is_valid_reel_url(url: str) -> bool:
    return normalize_instagram_url(url) is not None
