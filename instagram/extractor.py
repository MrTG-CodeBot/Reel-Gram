"""
Instagram Direct Message payload extractor.
Inspects incoming DM structures (clips, media shares, story shares, XMA objects, and links)
to extract canonical Instagram media URLs and direct CDN streaming endpoints.
"""

from typing import Optional, Dict, Any, Tuple
from instagrapi.types import DirectMessage
from downloader.validator import normalize_instagram_url
from config import logger


def extract_media_url_and_direct(message: DirectMessage) -> Tuple[Optional[str], Optional[str]]:
    """
    Parses a direct message to retrieve the media target URL and direct CDN URL if available.

    Returns:
        Tuple[Optional[str], Optional[str]]: (canonical_instagram_url, direct_cdn_url)
    """
    item_type = getattr(message, "item_type", "unknown") or "unknown"
    direct_cdn_url = None

    raw = {}
    try:
        raw = message.dict() if hasattr(message, "dict") else vars(message)
    except Exception:
        pass

    # Inspect XMA share payloads
    xma_share = getattr(message, "xma_share", None)
    if xma_share:
        for xma in (xma_share if isinstance(xma_share, list) else [xma_share]):
            target_url = getattr(xma, "video_url", None) or getattr(xma, "target_url", None) or (
                xma.get("video_url") or xma.get("target_url") if isinstance(xma, dict) else None
            )
            if target_url:
                normalized = normalize_instagram_url(target_url)
                if normalized:
                    return normalized, None

    raw_xma = getattr(message, "raw_xma", None)
    if not isinstance(raw_xma, dict):
        raw_xma = raw.get("raw_xma", {}) if isinstance(raw, dict) else {}

    if isinstance(raw_xma, dict):
        for xma_key in ("xma_story_share", "xma_media_share", "xma_clip", "generic_xma"):
            xma_items = raw_xma.get(xma_key)
            if xma_items:
                for item in (xma_items if isinstance(xma_items, list) else [xma_items]):
                    u = item.get("target_url") if isinstance(item, dict) else getattr(item, "target_url", None)
                    v = item.get("playable_url") or item.get("video_url") if isinstance(item, dict) else (
                        getattr(item, "playable_url", None) or getattr(item, "video_url", None)
                    )
                    if u and isinstance(u, str):
                        normalized = normalize_instagram_url(u)
                        if normalized:
                            return normalized, v
                    elif v and isinstance(v, str):
                        normalized = normalize_instagram_url(v)
                        if normalized:
                            return normalized, v

    # Direct clip / Reel shares
    clip = getattr(message, "clip", None)
    if clip:
        code = getattr(clip, "code", None)
        if code and isinstance(code, str):
            return f"https://www.instagram.com/reel/{code}/", None

    # Posts, Photos, or Carousels
    media_share = getattr(message, "media_share", None) or getattr(message, "media", None) or (
        raw.get("media_share") if isinstance(raw, dict) else None
    ) or (raw.get("media") if isinstance(raw, dict) else None)

    if media_share:
        code = getattr(media_share, "code", None)
        if not code and isinstance(media_share, dict):
            code = media_share.get("code")
        if code and isinstance(code, str):
            media_type = getattr(media_share, "media_type", None) or (media_share.get("media_type") if isinstance(media_share, dict) else None)
            url = f"https://www.instagram.com/reel/{code}/" if media_type == 2 else f"https://www.instagram.com/p/{code}/"
            return url, None

    # Stories and Highlights
    story_share = getattr(message, "story_share", None) or raw.get("story_share")
    if story_share:
        s_dict = story_share if isinstance(story_share, dict) else (
            story_share.dict() if hasattr(story_share, "dict") else vars(story_share)
        )
        media_info = s_dict.get("media") or s_dict
        if not isinstance(media_info, dict) and hasattr(media_info, "__dict__"):
            try:
                media_info = media_info.dict() if hasattr(media_info, "dict") else vars(media_info)
            except Exception:
                pass

        user_info = media_info.get("user") or s_dict.get("user") or {} if isinstance(media_info, dict) else {}
        username = user_info.get("username") if isinstance(user_info, dict) else getattr(user_info, "username", None)
        story_pk = media_info.get("pk") or media_info.get("id") or s_dict.get("reel_id") if isinstance(media_info, dict) else getattr(media_info, "pk", None)

        if isinstance(media_info, dict):
            v_vers = media_info.get("video_versions")
            if v_vers and isinstance(v_vers, list) and len(v_vers) > 0:
                direct_cdn_url = v_vers[0].get("url") if isinstance(v_vers[0], dict) else getattr(v_vers[0], "url", None)
            elif media_info.get("image_versions2", {}).get("candidates"):
                cands = media_info["image_versions2"]["candidates"]
                if cands and isinstance(cands, list) and len(cands) > 0:
                    direct_cdn_url = cands[0].get("url") if isinstance(cands[0], dict) else getattr(cands[0], "url", None)
            elif media_info.get("video_url"):
                direct_cdn_url = media_info.get("video_url")
            elif media_info.get("thumbnail_url"):
                direct_cdn_url = media_info.get("thumbnail_url")
        else:
            direct_cdn_url = getattr(media_info, "video_url", None) or getattr(media_info, "thumbnail_url", None)

        reel_id_str = str(s_dict.get("reel_id") or "")
        if "highlight:" in reel_id_str:
            highlight_id = reel_id_str.replace("highlight:", "").strip()
            return f"https://www.instagram.com/stories/highlights/{highlight_id}/", direct_cdn_url
        elif username and story_pk:
            clean_pk = str(story_pk).split("_")[0]
            return f"https://www.instagram.com/stories/{username}/{clean_pk}/", direct_cdn_url
        elif story_pk:
            clean_pk = str(story_pk).split("_")[0]
            return f"https://www.instagram.com/stories/_/{clean_pk}/", direct_cdn_url

    # Reshared Reel in Story
    reel_share = getattr(message, "reel_share", None) or raw.get("reel_share")
    if reel_share:
        r_dict = reel_share if isinstance(reel_share, dict) else (
            reel_share.dict() if hasattr(reel_share, "dict") else vars(reel_share)
        )
        media_info = r_dict.get("media") or {}
        code = media_info.get("code") or r_dict.get("code")
        if code:
            return f"https://www.instagram.com/reel/{code}/", None

    # Shared link preview
    link = getattr(message, "link", None)
    if link:
        link_text = getattr(link, "text", None)
        if link_text:
            normalized = normalize_instagram_url(link_text)
            if normalized:
                return normalized, None

        link_context = getattr(link, "link_context", None)
        if link_context:
            link_url = getattr(link_context, "link_url", None)
            if link_url:
                normalized = normalize_instagram_url(link_url)
                if normalized:
                    return normalized, None

    # Plaintext message containing an Instagram URL
    text = getattr(message, "text", None)
    if text:
        normalized = normalize_instagram_url(text)
        if normalized:
            return normalized, None

    return None, None


def extract_media_url_from_message(message: DirectMessage) -> Optional[str]:
    """Convenience helper extracting the canonical Instagram media URL."""
    url, _ = extract_media_url_and_direct(message)
    return url


extract_reel_url_from_message = extract_media_url_from_message
