import os
import shutil
import time
from pathlib import Path
from typing import Optional, List, Union
import yt_dlp
from config import DOWNLOAD_DIR, logger
from downloader.validator import detect_media_type, extract_media_code

def get_ffmpeg_executable() -> Optional[str]:
    """
    Finds the available FFmpeg executable.
    Checks system PATH first, then falls back to bundled imageio-ffmpeg binary.
    Also ensures the binary's directory is placed into PATH.
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
    Finds the available FFmpeg executable.
    Checks system PATH first, then falls back to bundled imageio-ffmpeg binary.
    Also ensures the binary's directory is placed into PATH.
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
    if d.get("status") == "downloading":
        downloaded = d.get("downloaded_bytes", 0)
        total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
        percent = (downloaded / total * 100) if total > 0 else 0
        speed = d.get("speed", 0)
        speed_mb = (speed / 1024 / 1024) if speed else 0
        logger.info(f"Downloading Media... {percent:.1f}% | Speed: {speed_mb:.2f} MB/s")
    elif d.get("status") == "finished":
        logger.info("Media download complete. Processing file(s)...")

def download_url_to_file(
    url: str,
    output_dir: Path = DOWNLOAD_DIR,
    default_ext: str = ".mp4",
    prefix: str = "insta"
) -> Optional[Path]:
    """
    Directly streams and downloads a media file from a CDN URL with proper headers
    and automatic media extension resolution (.mp4 or .jpg).
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
                logger.info(f"Direct stream download complete: {file_path.name} ({file_path.stat().st_size} bytes)")
                return file_path
    except Exception as e:
        logger.warning(f"Direct stream download failed for {url[:80]}...: {e}")
        
    return None

def _download_via_instagrapi(url: str, cl, direct_url: Optional[str] = None) -> List[Path]:
    """
    Downloads media using authenticated instagrapi Client for Stories, Highlights, Posts, or direct CDN URLs.
    """
    if not cl and not direct_url:
        return []
    
    downloaded_files: List[Path] = []
    
    # Priority 0: If direct CDN URL is available, download immediately
    if direct_url:
        logger.info(f"[instagrapi] Attempting download of direct CDN URL...")
        p = None
        if cl:
            try:
                p = cl.story_download_by_url(direct_url, folder=DOWNLOAD_DIR)
            except Exception as e:
                logger.debug(f"[instagrapi] cl.story_download_by_url failed for direct_url: {e}")
                
        if not p or not Path(p).exists():
            p = download_url_to_file(direct_url, output_dir=DOWNLOAD_DIR, prefix="direct_story")
            
        if p and Path(p).exists():
            downloaded_files.append(Path(p))
            logger.info(f"[instagrapi] Direct CDN download successful: {p}")
            return downloaded_files

    if not cl:
        return []

    m_type = detect_media_type(url)
    logger.info(f"[instagrapi] Processing {m_type} download from {url}")
    
    try:
        # 1. Story
        if m_type == "story":
            username, story_id = extract_story_details(url)
            logger.info(f"[instagrapi] Resolving Story: username={username}, story_id={story_id}")

            # Strategy 1A: If username is known and valid, query user_stories
            if username and username != "_":
                try:
                    user_id = cl.user_id_from_username(username)
                    if user_id:
                        user_stories = cl.user_stories(user_id)
                        logger.info(f"[instagrapi] Found {len(user_stories)} active story item(s) for @{username}")
                        
                        target_stories = []
                        if story_id:
                            for s in user_stories:
                                if str(s.pk) == str(story_id) or str(getattr(s, "id", "")).startswith(str(story_id)):
                                    target_stories.append(s)
                                    break
                                    
                        # If no specific story matched or no story_id provided, take all user stories
                        if not target_stories and not story_id and user_stories:
                            target_stories = user_stories

                        for s in target_stories:
                            media_type_code = getattr(s, "media_type", 1)
                            target_url = None
                            if media_type_code == 2 and getattr(s, "video_url", None):
                                target_url = str(s.video_url)
                            elif getattr(s, "thumbnail_url", None):
                                target_url = str(s.thumbnail_url)
                                
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
                                        default_ext=".mp4" if media_type_code == 2 else ".jpg",
                                        prefix=f"story_{username}_{s.pk}"
                                    )
                                    
                                if p and Path(p).exists():
                                    downloaded_files.append(Path(p))

                        if downloaded_files:
                            return downloaded_files
                except Exception as ue:
                    logger.warning(f"[instagrapi] Active stories fetch failed for @{username}: {ue}")

            # Strategy 1B: Fallback using story_id
            if story_id:
                try:
                    p = cl.story_download(str(story_id), folder=DOWNLOAD_DIR)
                    if p and Path(p).exists():
                        downloaded_files.append(Path(p))
                        return downloaded_files
                except Exception as se:
                    logger.debug(f"[instagrapi] Fallback story_download({story_id}) failed: {se}")

                try:
                    m_info = cl.media_info(story_id)
                    if m_info:
                        m_code = getattr(m_info, "media_type", 1)
                        t_url = str(m_info.video_url if m_code == 2 and m_info.video_url else m_info.thumbnail_url)
                        if t_url:
                            p = download_url_to_file(
                                t_url,
                                output_dir=DOWNLOAD_DIR,
                                default_ext=".mp4" if m_code == 2 else ".jpg",
                                prefix=f"story_{story_id}"
                            )
                            if p and Path(p).exists():
                                downloaded_files.append(Path(p))
                                return downloaded_files
                except Exception as me:
                    logger.debug(f"[instagrapi] Fallback media_info({story_id}) failed: {me}")

        # 2. Highlight
        elif m_type == "highlight":
            h_pk = extract_media_code(url)
            if h_pk:
                h_pk = str(h_pk).replace("highlight:", "").strip()
                logger.info(f"[instagrapi] Fetching highlight info for ID: {h_pk}")
                
                # Check if specific story within the highlight was linked
                _, query_story_id = extract_story_details(url)
                
                h_info = cl.highlight_info(h_pk)
                if h_info and getattr(h_info, "items", None):
                    items = h_info.items
                    logger.info(f"[instagrapi] Highlight {h_pk} contains {len(items)} item(s)")
                    
                    # If specific story_media_id was in the URL, filter to it
                    if query_story_id:
                        matched = [it for it in items if str(getattr(it, "pk", "")) == str(query_story_id)]
                        if matched:
                            items = matched
                            logger.info(f"[instagrapi] Filtered to specific highlight item: {query_story_id}")

                    for idx, item in enumerate(items):
                        try:
                            item_type = getattr(item, "media_type", 1)
                            target_url = None
                            if item_type == 2 and getattr(item, "video_url", None):
                                target_url = str(item.video_url)
                            elif getattr(item, "thumbnail_url", None):
                                target_url = str(item.thumbnail_url)
                                
                            if target_url:
                                p = None
                                try:
                                    p = cl.story_download_by_url(target_url, folder=DOWNLOAD_DIR)
                                except Exception as e_url:
                                    logger.debug(f"cl.story_download_by_url failed for item {idx}: {e_url}")

                                if not p or not Path(p).exists():
                                    p = download_url_to_file(
                                        target_url,
                                        output_dir=DOWNLOAD_DIR,
                                        default_ext=".mp4" if item_type == 2 else ".jpg",
                                        prefix=f"highlight_{h_pk}_{idx}"
                                    )

                                if p and Path(p).exists():
                                    downloaded_files.append(Path(p))
                        except Exception as item_err:
                            logger.warning(f"Failed downloading highlight item {idx}: {item_err}")
                            
                    if downloaded_files:
                        return downloaded_files

        # 3. Post / Reel / Carousel
        else:
            try:
                media_pk = cl.media_pk_from_url(url)
                media = cl.media_info(media_pk)
                m_code = getattr(media, "media_type", 1)
                
                # Album / Carousel (media_type == 8)
                if m_code == 8:
                    paths = cl.album_download(media_pk, folder=DOWNLOAD_DIR)
                    if paths:
                        downloaded_files = [Path(p) for p in paths if Path(p).exists()]
                        return downloaded_files
                # Video (media_type == 2)
                elif m_code == 2:
                    p = cl.video_download(media_pk, folder=DOWNLOAD_DIR)
                    if p and Path(p).exists():
                        downloaded_files.append(Path(p))
                        return downloaded_files
                # Photo (media_type == 1)
                else:
                    p = cl.photo_download(media_pk, folder=DOWNLOAD_DIR)
                    if p and Path(p).exists():
                        downloaded_files.append(Path(p))
                        return downloaded_files
            except Exception as pe:
                logger.warning(f"[instagrapi] Direct post download failed: {pe}")

    except Exception as e:
        logger.warning(f"[instagrapi] Fallback download failed: {e}")
        
    return downloaded_files

def download_media(
    url: str,
    cl=None,
    direct_url: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: int = 2
) -> List[Path]:
    """
    Universal media downloader for Instagram Reels, Posts (photo/video), Carousels (albums), Stories, and Highlights.
    Returns a List of Path objects for all downloaded media items.
    """
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    m_type = detect_media_type(url) or "media"
    logger.info(f"Initiating download for [{m_type.upper()}]: {url} (direct_url={'yes' if direct_url else 'no'})")

    # Priority 1: If direct CDN URL is provided, download directly
    if direct_url:
        direct_files = _download_via_instagrapi(url, cl=cl, direct_url=direct_url)
        if direct_files:
            logger.info(f"Direct CDN download succeeded with {len(direct_files)} file(s).")
            return direct_files

    # Priority 2: For Stories and Highlights, instagrapi session is the primary engine
    if m_type in ("story", "highlight") and cl:
        files = _download_via_instagrapi(url, cl)
        if files:
            logger.info(f"Successfully downloaded {len(files)} file(s) via instagrapi for {m_type}.")
            return files

    # Primary engine for Reels and standard video Posts: yt-dlp
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

    # Track files existing before download to find new files reliably
    before_files = set(DOWNLOAD_DIR.iterdir())

    for attempt in range(1, max_retries + 1):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                media_id = info.get("id") if info else None
                
                # Detect newly created files
                after_files = set(DOWNLOAD_DIR.iterdir())
                new_files = list(after_files - before_files)
                
                # Sort files naturally
                new_files.sort(key=lambda x: str(x))

                # Filter valid media extensions
                valid_media = [
                    f for f in new_files
                    if f.is_file() and f.suffix.lower() in [".mp4", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".webp"]
                ]

                if valid_media:
                    logger.info(f"Download successful! Captured {len(valid_media)} media file(s).")
                    return valid_media
                
                # Fallback: search directory for files matching media_id
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

    # Secondary engine: fallback to instagrapi if yt-dlp failed (essential for photo posts, carousels, stories, highlights)
    if cl:
        logger.info("Attempting instagrapi fallback download...")
        files = _download_via_instagrapi(url, cl, direct_url=direct_url)
        if files:
            return files

    return []

def download_reel(url: str, max_retries: int = 3, retry_delay: int = 2) -> Optional[Path]:
    """
    Backwards-compatible wrapper returning the first primary file path.
    """
    files = download_media(url, max_retries=max_retries, retry_delay=retry_delay)
    if files:
        return files[0]
    return None
