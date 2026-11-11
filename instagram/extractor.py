from typing import Optional, Dict, Any
from instagrapi.types import DirectMessage
from downloader.validator import normalize_instagram_url
from config import logger

def extract_media_url_from_message(message: DirectMessage) -> Optional[str]:
    """
    Inspects a DirectMessage object and extracts a canonical Instagram URL (Reel, Post, Story, or Highlight).
    Supports checking:
    1. XMA share (xma_clip, xma_media_share, xma_story_share) -> message.xma_share
    2. Direct Clip shared attachments -> message.clip
    3. Media / MediaShare attachments (Posts & Carousels) -> message.media_share / message.media
    4. Story shared attachments -> message.story_share
    5. Reel shared attachments -> message.reel_share
    6. Link objects -> message.link / message.link.link_context
    7. Plain text messages -> message.text
    """
    item_type = getattr(message, "item_type", "unknown") or "unknown"
    logger.info(f"[extractor] Inspecting message {message.id} | item_type={item_type}")

    # 1. XMA (Cross-Media Attachment) — modern format used when sharing Reels, Posts, Stories from the app
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
                    return normalized

    # Raw message dict fallback for XMA fields
    if item_type.startswith("xma_"):
        raw = None
        try:
            raw = message.dict() if hasattr(message, "dict") else vars(message)
        except Exception:
            pass
        if raw:
            for xma_key in ("xma_share", "xma_media_share", "xma_story_share"):
                xma_list = raw.get(xma_key)
                if xma_list:
                    for xma_item in (xma_list if isinstance(xma_list, list) else [xma_list]):
                        url = None
                        if isinstance(xma_item, dict):
                            url = xma_item.get("target_url") or xma_item.get("video_url") or xma_item.get("playable_url")
                        else:
                            url = getattr(xma_item, "target_url", None) or getattr(xma_item, "video_url", None)
                        if url:
                            normalized = normalize_instagram_url(url)
                            if normalized:
                                logger.info(f"[extractor] Extracted URL from raw[{xma_key}]: {normalized}")
                                return normalized

    # 2. Direct clip sharing (Instagram Reels)
    clip = getattr(message, "clip", None)
    if clip:
        code = getattr(clip, "code", None)
        if code:
            url = f"https://www.instagram.com/reel/{code}/"
            logger.info(f"[extractor] Extracted Reel URL from message.clip (code: {code}): {url}")
            return url

    # 3. MediaShare / Media (Posts, Photos, Carousels, or Videos)
    media_share = getattr(message, "media_share", None) or getattr(message, "media", None)
    if media_share:
        code = getattr(media_share, "code", None)
        if not code and isinstance(media_share, dict):
            code = media_share.get("code")
        if code:
            # Check media_type if available: 1=photo, 2=video, 8=album/carousel
            m_type = getattr(media_share, "media_type", None) or (media_share.get("media_type") if isinstance(media_share, dict) else None)
            if m_type == 2:
                url = f"https://www.instagram.com/reel/{code}/"
            else:
                url = f"https://www.instagram.com/p/{code}/"
            logger.info(f"[extractor] Extracted Post URL from media_share (code: {code}, type: {m_type}): {url}")
            return url

    # 4. StoryShare (Stories and Highlights)
    story_share = getattr(message, "story_share", None)
    if story_share:
        # story_share can be dict or object
        s_dict = story_share if isinstance(story_share, dict) else (story_share.dict() if hasattr(story_share, "dict") else vars(story_share))
        media_info = s_dict.get("media") or s_dict
        user_info = media_info.get("user") or s_dict.get("user") or {}
        username = user_info.get("username") if isinstance(user_info, dict) else getattr(user_info, "username", None)
        story_pk = media_info.get("pk") or media_info.get("id") or s_dict.get("reel_id")
        
        # Check if it is a highlight
        reel_id_str = str(s_dict.get("reel_id") or "")
        if "highlight:" in reel_id_str:
            highlight_id = reel_id_str.replace("highlight:", "")
            url = f"https://www.instagram.com/stories/highlights/{highlight_id}/"
            logger.info(f"[extractor] Extracted Highlight URL from story_share: {url}")
            return url
        elif username and story_pk:
            url = f"https://www.instagram.com/stories/{username}/{story_pk}/"
            logger.info(f"[extractor] Extracted Story URL from story_share: {url}")
            return url

    # 5. ReelShare (Story containing a reel or reel reshared to story)
    reel_share = getattr(message, "reel_share", None)
    if reel_share:
        r_dict = reel_share if isinstance(reel_share, dict) else (reel_share.dict() if hasattr(reel_share, "dict") else vars(reel_share))
        media_info = r_dict.get("media") or {}
        code = media_info.get("code") or r_dict.get("code")
        if code:
            url = f"https://www.instagram.com/reel/{code}/"
            logger.info(f"[extractor] Extracted Reel URL from reel_share: {url}")
            return url

    # 6. Message Link object (shared links that Instagram parses)
    link = getattr(message, "link", None)
    if link:
        link_text = getattr(link, "text", None)
        if link_text:
            normalized = normalize_instagram_url(link_text)
            if normalized:
                logger.info(f"[extractor] Extracted URL from message.link.text: {normalized}")
                return normalized

        link_context = getattr(link, "link_context", None)
        if link_context:
            link_url = getattr(link_context, "link_url", None)
            if link_url:
                normalized = normalize_instagram_url(link_url)
                if normalized:
                    logger.info(f"[extractor] Extracted URL from message.link.link_context.link_url: {normalized}")
                    return normalized

    # 7. Text field (regular message containing URL string)
    text = getattr(message, "text", None)
    if text:
        normalized = normalize_instagram_url(text)
        if normalized:
            logger.info(f"[extractor] Extracted URL from message.text: {normalized}")
            return normalized

    return None

# Backwards compatibility alias
extract_reel_url_from_message = extract_media_url_from_message
