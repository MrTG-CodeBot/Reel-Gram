"""
Media download orchestrator for Instagram Reels, Posts, Carousels, Stories, and Highlights.
Uses yt-dlp as the primary download engine for public video streams, with instagrapi
and direct HTTP streaming fallbacks for authenticated items, stories, and image carousels.
"""

import os
import shutil
import time
import uuid
import requests
from pathlib import Path
from typing import Optional, List, Union
import yt_dlp
from config import DOWNLOAD_DIR, logger
from downloader.validator import detect_media_type, extract_media_code, extract_story_details


def get_ffmpeg_executable() -> Optional[str]:
    """
    Locates the FFmpeg binary on the system.
    Checks the system PATH first, then falls back to bundled imageio-ffmpeg.
    """
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_exe and Path(ffmpeg_exe).exists():
            bin_dir = str(Path(ffmpeg_exe).parent)
            if bin_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            return ffmpeg_exe
    except Exception as e:
        logger.debug(f"Could not load imageio-ffmpeg: {e}")

    return None


def progress_hook(d: dict) -> None:
    """Logs download progress percentage and transfer speed."""
    if d.get("status") == "downloading":
        downloaded = d.get("downloaded_bytes", 0)
        total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
        percent = (downloaded / total * 100) if total > 0 else 0
        speed = d.get("speed", 0)
        speed_mb = (speed / 1024 / 1024) if speed else 0
        logger.info(f"Downloading media: {percent:.1f}% | {speed_mb:.2f} MB/s")
    elif d.get("status") == "finished":
        logger.info("Download finished. Processing file...")


def download_url_to_file(
    url: str,
    output_dir: Path = DOWNLOAD_DIR,
    default_ext: str = ".mp4",
    prefix: str = "insta"
) -> Optional[Path]:
    """
    Streams a media file from a direct CDN URL and saves it to local disk.
    Automatically resolves file extensions from HTTP response headers.
    """
    if not url:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*"
    }

    try:
        with requests.get(url, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            content_type = r.headers.get("content-type", "").lower()

            ext = default_ext
            if "video" in content_type:
                ext = ".mp4"
            elif "image" in content_type:
                ext = ".jpg"
            elif "." in url.split("?")[0].split("/")[-1]:
                guessed = "." + url.split("?")[0].split("/")[-1].split(".")[-1].lower()
                if guessed in [".mp4", ".jpg", ".jpeg", ".png", ".webp"]:
                    ext = guessed

            filename = f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
            file_path = output_dir / filename

            with open(file_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

            if file_path.exists() and file_path.stat().st_size > 0:
                logger.info(f"Direct stream download saved: {file_path.name} ({file_path.stat().st_size} bytes)")
                return file_path
    except Exception as e:
        logger.warning(f"Direct stream download failed for {url[:80]}: {e}")

    return None


def _download_via_instagrapi(url: str, cl, direct_url: Optional[str] = None) -> List[Path]:
    """
    Fallback downloader utilizing an authenticated instagrapi Client.
    Handles Stories, Highlights, image carousels, and private media.
    """
    if not cl and not direct_url:
        return []

    downloaded_files: List[Path] = []

    # If the DM payload contained a direct CDN URL, fetch it first
    if direct_url:
        p = None
        if cl:
            try:
                p = cl.story_download_by_url(direct_url, folder=DOWNLOAD_DIR)
            except Exception as e:
                logger.debug(f"cl.story_download_by_url failed for direct_url: {e}")

        if not p or not Path(p).exists():
            p = download_url_to_file(direct_url, output_dir=DOWNLOAD_DIR, prefix="direct_story")

        if p and Path(p).exists():
            downloaded_files.append(Path(p))
            return downloaded_files

    if not cl:
        return []

    media_type = detect_media_type(url)

    try:
        if media_type == "story":
            username, story_id = extract_story_details(url)

            # Query user stories if username is available
            if username and username != "_":
                try:
                    user_id = cl.user_id_from_username(username)
                    if user_id:
                        user_stories = cl.user_stories(user_id)
                        target_stories = []

                        if story_id:
                            for s in user_stories:
                                if str(s.pk) == str(story_id) or str(getattr(s, "id", "")).startswith(str(story_id)):
                                    target_stories.append(s)
                                    break

                        if not target_stories and not story_id and user_stories:
                            target_stories = user_stories

                        for s in target_stories:
                            is_video = getattr(s, "media_type", 1) == 2
                            target_url = str(s.video_url if is_video and s.video_url else s.thumbnail_url)

                            if target_url:
                                p = None
                                try:
                                    p = cl.story_download_by_url(target_url, folder=DOWNLOAD_DIR)
                                except Exception as ue:
                                    logger.debug(f"cl.story_download_by_url failed: {ue}")

                                if not p or not Path(p).exists():
                                    p = download_url_to_file(
                                        target_url,
                                        output_dir=DOWNLOAD_DIR,
                                        default_ext=".mp4" if is_video else ".jpg",
                                        prefix=f"story_{username}_{s.pk}"
                                    )

                                if p and Path(p).exists():
                                    downloaded_files.append(Path(p))

                        if downloaded_files:
                            return downloaded_files
                except Exception as ue:
                    logger.warning(f"Active stories fetch failed for @{username}: {ue}")

            # Fallback by story ID directly
            if story_id:
                try:
                    p = cl.story_download(str(story_id), folder=DOWNLOAD_DIR)
                    if p and Path(p).exists():
                        downloaded_files.append(Path(p))
                        return downloaded_files
                except Exception as se:
                    logger.debug(f"Fallback story_download({story_id}) failed: {se}")

                try:
                    media_info = cl.media_info(story_id)
                    if media_info:
                        is_video = getattr(media_info, "media_type", 1) == 2
                        target_url = str(media_info.video_url if is_video and media_info.video_url else media_info.thumbnail_url)
                        if target_url:
                            p = download_url_to_file(
                                target_url,
                                output_dir=DOWNLOAD_DIR,
                                default_ext=".mp4" if is_video else ".jpg",
                                prefix=f"story_{story_id}"
                            )
                            if p and Path(p).exists():
                                downloaded_files.append(Path(p))
                                return downloaded_files
                except Exception as me:
                    logger.debug(f"Fallback media_info({story_id}) failed: {me}")

        elif media_type == "highlight":
            h_pk = extract_media_code(url)
            if h_pk:
                h_pk = str(h_pk).replace("highlight:", "").strip()
                _, query_story_id = extract_story_details(url)

                highlight_info = cl.highlight_info(h_pk)
                if highlight_info and getattr(highlight_info, "items", None):
                    items = highlight_info.items

                    # If a specific story inside the highlight was linked, filter to it
                    if query_story_id:
                        matched = [it for it in items if str(getattr(it, "pk", "")) == str(query_story_id)]
                        if matched:
                            items = matched

                    for idx, item in enumerate(items):
                        try:
                            is_video = getattr(item, "media_type", 1) == 2
                            target_url = str(item.video_url if is_video and item.video_url else item.thumbnail_url)

                            if target_url:
                                p = None
                                try:
                                    p = cl.story_download_by_url(target_url, folder=DOWNLOAD_DIR)
                                except Exception as e_url:
                                    logger.debug(f"cl.story_download_by_url failed for highlight item {idx}: {e_url}")

                                if not p or not Path(p).exists():
                                    p = download_url_to_file(
                                        target_url,
                                        output_dir=DOWNLOAD_DIR,
                                        default_ext=".mp4" if is_video else ".jpg",
                                        prefix=f"highlight_{h_pk}_{idx}"
                                    )

                                if p and Path(p).exists():
                                    downloaded_files.append(Path(p))
                        except Exception as item_err:
                            logger.warning(f"Failed downloading highlight item {idx}: {item_err}")

                    if downloaded_files:
                        return downloaded_files

        else:
            # Standard post or album download
            try:
                media_pk = cl.media_pk_from_url(url)
                media = cl.media_info(media_pk)
                media_type_code = getattr(media, "media_type", 1)

                if media_type_code == 8:  # Carousel / Album
                    paths = cl.album_download(media_pk, folder=DOWNLOAD_DIR)
                    if paths:
                        downloaded_files = [Path(p) for p in paths if Path(p).exists()]
                        return downloaded_files
                elif media_type_code == 2:  # Video
                    p = cl.video_download(media_pk, folder=DOWNLOAD_DIR)
                    if p and Path(p).exists():
                        downloaded_files.append(Path(p))
                        return downloaded_files
                else:  # Photo
                    p = cl.photo_download(media_pk, folder=DOWNLOAD_DIR)
                    if p and Path(p).exists():
                        downloaded_files.append(Path(p))
                        return downloaded_files
            except Exception as pe:
                logger.warning(f"Direct post download failed via instagrapi: {pe}")

    except Exception as e:
        logger.warning(f"instagrapi download failed: {e}")

    return downloaded_files


def download_media(
    url: str,
    cl=None,
    direct_url: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: int = 2
) -> List[Path]:
    """
    Downloads media from an Instagram URL.
    Returns a list of local Path objects representing downloaded files.
    """
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    media_type = detect_media_type(url) or "media"
    logger.info(f"Downloading [{media_type.upper()}]: {url}")

    if direct_url:
        direct_files = _download_via_instagrapi(url, cl=cl, direct_url=direct_url)
        if direct_files:
            return direct_files

    if media_type in ("story", "highlight") and cl:
        files = _download_via_instagrapi(url, cl)
        if files:
            return files

    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": str(DOWNLOAD_DIR / "%(id)s_%(autonumber)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
        "merge_output_format": "mp4",
        "socket_timeout": 30,
    }

    ffmpeg_path = get_ffmpeg_executable()
    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path

    before_files = set(DOWNLOAD_DIR.iterdir())

    for attempt in range(1, max_retries + 1):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                media_id = info.get("id") if info else None

                after_files = set(DOWNLOAD_DIR.iterdir())
                new_files = sorted(list(after_files - before_files), key=lambda x: str(x))

                valid_media = [
                    f for f in new_files
                    if f.is_file() and f.suffix.lower() in [".mp4", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".webp"]
                ]

                if valid_media:
                    return valid_media

                if media_id:
                    matched = [
                        f for f in DOWNLOAD_DIR.iterdir()
                        if f.is_file() and f.name.startswith(media_id) and f.suffix.lower() in [".mp4", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".webp"]
                    ]
                    if matched:
                        return sorted(matched, key=lambda x: str(x))

        except Exception as e:
            logger.warning(f"yt-dlp attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                time.sleep(retry_delay)

    # Fallback to instagrapi if yt-dlp fails (common for photos and carousels)
    if cl:
        files = _download_via_instagrapi(url, cl, direct_url=direct_url)
        if files:
            return files

    return []


def download_reel(url: str, max_retries: int = 3, retry_delay: int = 2) -> Optional[Path]:
    """Convenience wrapper returning the first downloaded file path."""
    files = download_media(url, max_retries=max_retries, retry_delay=retry_delay)
    return files[0] if files else None
