"""
URL validation and parsing utilities for Instagram links.
Supports Reels, Posts, Stories, Highlights, and shortlink formats.
"""

import re
import base64
from typing import Optional, Tuple
from config import logger

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
    Decodes base64-encoded shortlink tokens used in Instagram /s/ URLs.
    Example: aGlnaGxpZ2h0OjE3OTg3... decodes to highlight:17987...
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
        if "highlight:" in decoded:
            return decoded.split("highlight:")[1].split("?")[0].strip()
        if "story:" in decoded:
            return decoded.split("story:")[1].split("?")[0].strip()
        return decoded.split("?")[0].strip()
    except Exception:
        return None


def detect_media_type(url: str) -> Optional[str]:
    """
    Identifies the media classification from an Instagram URL.
    Returns 'reel', 'post', 'highlight', 'story', or None if unrecognized.
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
    Parses a Story URL to extract the username and media ID.
    Handles standard /stories/{user}/{id} as well as ?story_media_id= query parameters.
    """
    if not url:
        return None, None

    qid_match = re.search(r"[?&]story_media_id=([0-9_]+)", url)
    query_story_id = qid_match.group(1).split("_")[0] if qid_match else None

    match = re.search(r"instagram\.com/stories/(?!highlights/)([A-Za-z0-9_.\-]+)(?:/([0-9_]+))?", url, re.IGNORECASE)
    if match:
        username = match.group(1)
        raw_story_id = match.group(2) or query_story_id
        story_id = raw_story_id.split("_")[0] if raw_story_id else None
        return username, story_id

    return None, query_story_id


def extract_media_code(url: str) -> Optional[str]:
    """
    Extracts the unique shortcode or primary identifier from an Instagram URL.
    """
    if not url:
        return None

    for pattern in REEL_PATTERNS + POST_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)

    match_shortlink = re.search(r"instagram\.com/s/([A-Za-z0-9_\-]+)", url, re.IGNORECASE)
    if match_shortlink:
        decoded = resolve_shortlink_id(match_shortlink.group(1))
        if decoded:
            return decoded.replace("highlight:", "")
        return match_shortlink.group(1)

    match_highlight = re.search(r"instagram\.com/stories/highlights/([0-9A-Za-z_\-]+)", url, re.IGNORECASE)
    if match_highlight:
        return match_highlight.group(1).replace("highlight:", "")

    username, story_id = extract_story_details(url)
    if story_id:
        return story_id
    if username:
        return username

    return None


def normalize_instagram_url(url: str) -> Optional[str]:
    """
    Cleans tracking parameters from an Instagram link and returns a canonical URL.
    """
    if not url or not isinstance(url, str):
        return None

    for pattern in REEL_PATTERNS:
        m = pattern.search(url)
        if m:
            return f"https://www.instagram.com/reel/{m.group(1)}/"

    for pattern in POST_PATTERNS:
        m = pattern.search(url)
        if m:
            return f"https://www.instagram.com/p/{m.group(1)}/"

    match_short = re.search(r"instagram\.com/s/([A-Za-z0-9_\-]+)", url, re.IGNORECASE)
    if match_short:
        decoded = resolve_shortlink_id(match_short.group(1))
        if decoded:
            return f"https://www.instagram.com/stories/highlights/{decoded}/"
        return f"https://www.instagram.com/s/{match_short.group(1)}/"

    match_hl = re.search(r"instagram\.com/stories/highlights/([0-9A-Za-z_\-]+)", url, re.IGNORECASE)
    if match_hl:
        hl_id = match_hl.group(1).replace("highlight:", "")
        return f"https://www.instagram.com/stories/highlights/{hl_id}/"

    username, story_id = extract_story_details(url)
    if username and story_id:
        return f"https://www.instagram.com/stories/{username}/{story_id}/"
    elif username:
        return f"https://www.instagram.com/stories/{username}/"

    return None


def extract_reel_code(url: str) -> Optional[str]:
    return extract_media_code(url)


def normalize_reel_url(url: str) -> Optional[str]:
    return normalize_instagram_url(url)


def is_valid_reel_url(url: str) -> bool:
    return normalize_instagram_url(url) is not None
