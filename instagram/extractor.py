from typing import Optional
from instagrapi.types import DirectMessage
from downloader.validator import normalize_reel_url
from config import logger

def extract_reel_url_from_message(message: DirectMessage) -> Optional[str]:
    """
    Inspects a DirectMessage object and extracts a canonical Instagram Reel URL if present.
    Supports checking:
    1. XMA share (xma_clip, xma_reel_share) - modern Instagram DM format -> message.xma_share
    2. Direct Clip shared attachments -> message.clip
    3. Media shared attachments -> message.media
    4. Link objects -> message.link / message.link.link_context
    5. Plain text messages -> message.text
    """
    item_type = getattr(message, "item_type", "unknown") or "unknown"
    logger.info(f"[extractor] Inspecting message {message.id} | item_type={item_type}")

    # 1. XMA (Cross-Media Attachment) — modern format used when sharing Reels from the app
    # item_type is "xma_clip", "xma_reel_share", etc.
    xma_share = getattr(message, "xma_share", None)
    logger.info(f"[extractor]   xma_share={xma_share!r}")
    if xma_share:
        for xma in (xma_share if isinstance(xma_share, list) else [xma_share]):
            # MediaXma object uses video_url (not target_url)
            target_url = getattr(xma, "video_url", None) or getattr(xma, "target_url", None) or (xma.get("video_url") or xma.get("target_url") if isinstance(xma, dict) else None)
            logger.info(f"[extractor]   xma video_url={target_url!r}")
            if target_url:
                normalized = normalize_reel_url(target_url)
                if normalized:
                    logger.info(f"[extractor] Extracted Reel URL from xma_share.target_url: {normalized}")
                    return normalized

    # Also try fetching xma_share from the raw message dict if instagrapi didn't map it
    if item_type.startswith("xma_"):
        # Try accessing via __dict__ or dict() to get unmapped fields
        raw = None
        try:
            raw = message.dict() if hasattr(message, "dict") else vars(message)
        except Exception:
            pass
        if raw:
            for xma_key in ("xma_share", "xma_media_share"):
                xma_list = raw.get(xma_key)
                logger.info(f"[extractor]   raw[{xma_key!r}]={xma_list!r}")
                if xma_list:
                    for xma_item in (xma_list if isinstance(xma_list, list) else [xma_list]):
                        url = None
                        if isinstance(xma_item, dict):
                            url = xma_item.get("video_url") or xma_item.get("target_url") or xma_item.get("playable_url")
                        else:
                            url = getattr(xma_item, "video_url", None) or getattr(xma_item, "target_url", None)
                        logger.info(f"[extractor]   xma_item video_url={url!r}")
                        if url:
                            normalized = normalize_reel_url(url)
                            if normalized:
                                logger.info(f"[extractor] Extracted Reel URL from raw xma_share: {normalized}")
                                return normalized

    # 2. Direct clip sharing (e.g. shared from Instagram Reels feed)
    clip = getattr(message, "clip", None)
    logger.info(f"[extractor]   clip={clip!r}")
    if clip:
        code = getattr(clip, "code", None)
        if code:
            url = f"https://www.instagram.com/reel/{code}/"
            logger.info(f"[extractor] Extracted Reel URL from message.clip (shortcode: {code})")
            return url

    # 3. General media sharing (e.g. post/video share)
    media = getattr(message, "media", None)
    logger.info(f"[extractor]   media={media!r}")
    if media:
        code = getattr(media, "code", None)
        if code:
            url = f"https://www.instagram.com/reel/{code}/"
            logger.info(f"[extractor] Extracted Reel URL from message.media (shortcode: {code})")
            return url

    # 4. Message Link object (shared links that Instagram parses)
    link = getattr(message, "link", None)
    logger.info(f"[extractor]   link={link!r}")
    if link:
        link_text = getattr(link, "text", None)
        logger.info(f"[extractor]   link.text={link_text!r}")
        if link_text:
            normalized = normalize_reel_url(link_text)
            if normalized:
                logger.info(f"[extractor] Extracted Reel URL from message.link.text: {normalized}")
                return normalized

        link_context = getattr(link, "link_context", None)
        logger.info(f"[extractor]   link.link_context={link_context!r}")
        if link_context:
            link_url = getattr(link_context, "link_url", None)
            logger.info(f"[extractor]   link.link_context.link_url={link_url!r}")
            if link_url:
                normalized = normalize_reel_url(link_url)
                if normalized:
                    logger.info(f"[extractor] Extracted Reel URL from message.link.link_context.link_url: {normalized}")
                    return normalized

    # 5. Text field (regular message containing URL string)
    text = getattr(message, "text", None)
    logger.info(f"[extractor]   text={text!r}")
    if text:
        normalized = normalize_reel_url(text)
        if normalized:
            logger.info(f"[extractor] Extracted Reel URL from message.text: {normalized}")
            return normalized

    logger.info(f"[extractor] No Reel URL found in message {message.id}")
    return None
