from typing import Optional, Dict, Any, Tuple
from instagrapi.types import DirectMessage
from downloader.validator import normalize_instagram_url
from config import logger

def extract_media_url_and_direct(message: DirectMessage) -> Tuple[Optional[str], Optional[str]]:
    """
    Inspects a DirectMessage object and extracts:
    1. A canonical Instagram URL (Reel, Post, Story, or Highlight).
    2. A direct media CDN URL (if present in payload, e.g. for Stories).
    """
    item_type = getattr(message, "item_type", "unknown") or "unknown"
    logger.info(f"[extractor] Inspecting message {message.id} | item_type={item_type}")

    direct_cdn_url = None

    # Helper to check raw dict
    raw = {}
    try:
        raw = message.dict() if hasattr(message, "dict") else vars(message)
    except Exception:
        pass

    # 1. Check XMA Share (xma_clip, xma_media_share, xma_story_share, generic_xma)
    xma_share = getattr(message, "xma_share", None)
    if xma_share:
        for xma in (xma_share if isinstance(xma_share, list) else [xma_share]):
            target_url = getattr(xma, "video_url", None) or getattr(xma, "target_url", None) or (
                xma.get("video_url") or xma.get("target_url") if isinstance(xma, dict) else None
            )
            if target_url:
                normalized = normalize_instagram_url(target_url)
                if normalized:
                    logger.info(f"[extractor] Extracted URL from xma_share: {normalized}")
                    return normalized, None

    # Check raw_xma or raw dictionary for xma fields
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
                            logger.info(f"[extractor] Extracted URL from raw_xma[{xma_key}]: {normalized} (direct_cdn={'yes' if v else 'no'})")
                            return normalized, v
                    elif v and isinstance(v, str):
                        normalized = normalize_instagram_url(v)
                        if normalized:
                            return normalized, v

    # 2. Direct clip sharing (Reels)
    clip = getattr(message, "clip", None)
    if clip:
        code = getattr(clip, "code", None)
        if code and isinstance(code, str):
            url = f"https://www.instagram.com/reel/{code}/"
            logger.info(f"[extractor] Extracted Reel URL from message.clip (code: {code}): {url}")
            return url, None

    # 3. MediaShare / Media (Posts, Photos, Carousels, or Videos)
    media_share = getattr(message, "media_share", None) or getattr(message, "media", None) or (
        raw.get("media_share") if isinstance(raw, dict) else None
    ) or (raw.get("media") if isinstance(raw, dict) else None)
    if media_share:
        code = getattr(media_share, "code", None)
        if not code and isinstance(media_share, dict):
            code = media_share.get("code")
        if code and isinstance(code, str):
            m_type = getattr(media_share, "media_type", None) or (media_share.get("media_type") if isinstance(media_share, dict) else None)
            url = f"https://www.instagram.com/reel/{code}/" if m_type == 2 else f"https://www.instagram.com/p/{code}/"
            logger.info(f"[extractor] Extracted Post URL from media_share (code: {code}, type: {m_type}): {url}")
            return url, None

    # 4. StoryShare (Stories and Highlights)
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

        # Extract direct CDN URL from media if available
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

        # Check if it is a highlight
        reel_id_str = str(s_dict.get("reel_id") or "")
        if "highlight:" in reel_id_str:
            highlight_id = reel_id_str.replace("highlight:", "").strip()
            url = f"https://www.instagram.com/stories/highlights/{highlight_id}/"
            logger.info(f"[extractor] Extracted Highlight URL from story_share: {url} (direct_cdn={'yes' if direct_cdn_url else 'no'})")
            return url, direct_cdn_url
        elif username and story_pk:
            clean_pk = str(story_pk).split("_")[0]
            url = f"https://www.instagram.com/stories/{username}/{clean_pk}/"
            logger.info(f"[extractor] Extracted Story URL from story_share: {url} (direct_cdn={'yes' if direct_cdn_url else 'no'})")
            return url, direct_cdn_url
        elif story_pk:
            clean_pk = str(story_pk).split("_")[0]
            url = f"https://www.instagram.com/stories/_/{clean_pk}/"
            logger.info(f"[extractor] Extracted Story URL with story_pk: {url} (direct_cdn={'yes' if direct_cdn_url else 'no'})")
            return url, direct_cdn_url

    # 5. ReelShare (Story containing a reel or reel reshared to story)
    reel_share = getattr(message, "reel_share", None) or raw.get("reel_share")
    if reel_share:
        r_dict = reel_share if isinstance(reel_share, dict) else (
            reel_share.dict() if hasattr(reel_share, "dict") else vars(reel_share)
        )
        media_info = r_dict.get("media") or {}
        code = media_info.get("code") or r_dict.get("code")
        if code:
            url = f"https://www.instagram.com/reel/{code}/"
            logger.info(f"[extractor] Extracted Reel URL from reel_share: {url}")
            return url, None

    # 6. Message Link object
    link = getattr(message, "link", None)
    if link:
        link_text = getattr(link, "text", None)
        if link_text:
            normalized = normalize_instagram_url(link_text)
            if normalized:
                logger.info(f"[extractor] Extracted URL from message.link.text: {normalized}")
                return normalized, None

        link_context = getattr(link, "link_context", None)
        if link_context:
            link_url = getattr(link_context, "link_url", None)
            if link_url:
                normalized = normalize_instagram_url(link_url)
                if normalized:
                    logger.info(f"[extractor] Extracted URL from message.link.link_context.link_url: {normalized}")
                    return normalized, None

    # 7. Text field (e.g. user pasted URL)
    text = getattr(message, "text", None)
    if text:
        normalized = normalize_instagram_url(text)
        if normalized:
            logger.info(f"[extractor] Extracted URL from message.text: {normalized}")
            return normalized, None

    return None, None

def extract_media_url_from_message(message: DirectMessage) -> Optional[str]:
    url, _ = extract_media_url_and_direct(message)
    return url

# Backwards compatibility alias
extract_reel_url_from_message = extract_media_url_from_message
