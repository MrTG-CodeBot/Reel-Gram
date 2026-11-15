import re
import base64
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

HIGHLIGHT_PATTERNS = [
    re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/stories/highlights/([0-9A-Za-z_\-]+)", re.IGNORECASE),
    re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/s/([0-9A-Za-z_\-]+)", re.IGNORECASE),
]

STORY_PATTERNS = [
    re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/stories/(?!highlights/)([A-Za-z0-9_.\-]+)/([0-9_]+)", re.IGNORECASE),
    re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/stories/(?!highlights/)([A-Za-z0-9_.\-]+)", re.IGNORECASE),
    re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/share/story/([A-Za-z0-9_\-]+)", re.IGNORECASE),
]

def resolve_shortlink_id(token: str) -> Optional[str]:
    """
    Decodes base64 tokens used in Instagram /s/ shortlinks.
    Example: aGlnaGxpZ2h0OjE3OTg3... -> highlight:17987...
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        dec = base64.b64decode(padded).decode("utf-8", errors="ignore")
        if "highlight:" in dec:
            return dec.split("highlight:")[1].split("?")[0].strip()
        if "story:" in dec:
            return dec.split("story:")[1].split("?")[0].strip()
        return dec.split("?")[0].strip()
    except Exception:
        return None

def detect_media_type(url: str) -> Optional[str]:
    """
    Detects the media type from the given Instagram URL.
    Returns: 'reel', 'post', 'highlight', 'story', or None.
    """
    if not url:
        return None
    for pattern in REEL_PATTERNS:
        if pattern.search(url):
            return "reel"
    for pattern in POST_PATTERNS:
        if pattern.search(url):
            return "post"
    for pattern in HIGHLIGHT_PATTERNS:
        if pattern.search(url):
            return "highlight"
    for pattern in STORY_PATTERNS:
        if pattern.search(url):
            return "story"
    return None

def extract_story_details(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts (username, story_id) from an Instagram Story URL.
    Handles query params like ?story_media_id=... and compounds like pk_userid.
    """
    if not url:
        return None, None
        
    # Check for ?story_media_id=... query parameter
    qid_match = re.search(r"[?&]story_media_id=([0-9_]+)", url)
    query_story_id = qid_match.group(1).split("_")[0] if qid_match else None

    # Check /stories/{username}/{story_id} (ignoring /stories/highlights/)
    m = re.search(r"instagram\.com/stories/(?!highlights/)([A-Za-z0-9_.\-]+)(?:/([0-9_]+))?", url, re.IGNORECASE)
    if m:
        username = m.group(1)
        raw_story_id = m.group(2) or query_story_id
        story_id = raw_story_id.split("_")[0] if raw_story_id else None
        return username, story_id
        
    return None, query_story_id

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
    
    # Check highlights
    m_s = re.search(r"instagram\.com/s/([A-Za-z0-9_\-]+)", url, re.IGNORECASE)
    if m_s:
        decoded = resolve_shortlink_id(m_s.group(1))
        if decoded:
            return decoded.replace("highlight:", "")
        return m_s.group(1)

    m_hl = re.search(r"instagram\.com/stories/highlights/([0-9A-Za-z_\-]+)", url, re.IGNORECASE)
    if m_hl:
        return m_hl.group(1).replace("highlight:", "")
        
    # Check stories
    username, story_id = extract_story_details(url)
    if story_id:
        return story_id
    if username:
        return username
        
    return None

def normalize_instagram_url(url: str) -> Optional[str]:
    """
    Validates the URL format, removes tracking/query parameters, and returns
    a standardized canonical Instagram URL for Reels, Posts, Stories, or Highlights.
    """
    if not url or not isinstance(url, str):
        return None
        
    # 1. Reels
    for pattern in REEL_PATTERNS:
        m = pattern.search(url)
        if m:
            return f"https://www.instagram.com/reel/{m.group(1)}/"
            
    # 2. Posts
    for pattern in POST_PATTERNS:
        m = pattern.search(url)
        if m:
            return f"https://www.instagram.com/p/{m.group(1)}/"
            
    # 3. Highlights
    m_s = re.search(r"instagram\.com/s/([A-Za-z0-9_\-]+)", url, re.IGNORECASE)
    if m_s:
        dec = resolve_shortlink_id(m_s.group(1))
        if dec:
            return f"https://www.instagram.com/stories/highlights/{dec}/"
        return f"https://www.instagram.com/s/{m_s.group(1)}/"

    m_hl = re.search(r"instagram\.com/stories/highlights/([0-9A-Za-z_\-]+)", url, re.IGNORECASE)
    if m_hl:
        hl_id = m_hl.group(1).replace("highlight:", "")
        return f"https://www.instagram.com/stories/highlights/{hl_id}/"
        
    # 4. Stories
    username, story_id = extract_story_details(url)
    if username and story_id:
        return f"https://www.instagram.com/stories/{username}/{story_id}/"
    elif username:
        return f"https://www.instagram.com/stories/{username}/"
        
    return None

# Backwards compatibility wrappers
def extract_reel_code(url: str) -> Optional[str]:
    return extract_media_code(url)

def normalize_reel_url(url: str) -> Optional[str]:
    return normalize_instagram_url(url)

def is_valid_reel_url(url: str) -> bool:
    return normalize_instagram_url(url) is not None
