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

def _download_via_instagrapi(url: str, cl) -> List[Path]:
    """
    Downloads media using authenticated instagrapi Client for Stories, Highlights, or private media.
    """
    if not cl:
        return []
    
    m_type = detect_media_type(url)
    logger.info(f"[instagrapi] Attempting fallback download for {m_type} from {url}")
    downloaded_files: List[Path] = []
    
    try:
        # 1. Story
        if m_type == "story":
            story_pk = extract_media_code(url)
            if story_pk:
                p = cl.story_download(str(story_pk), folder=DOWNLOAD_DIR)
                if p and Path(p).exists():
                    downloaded_files.append(Path(p))
                    return downloaded_files

        # 2. Highlight
        elif m_type == "highlight":
            h_pk = extract_media_code(url)
            if h_pk:
                # Resolve highlight info
                h_info = cl.highlight_info(h_pk)
                if h_info and getattr(h_info, "items", None):
                    for item in h_info.items:
                        try:
                            item_pk = getattr(item, "pk", None)
                            if item_pk:
                                p = cl.story_download(str(item_pk), folder=DOWNLOAD_DIR)
                                if p and Path(p).exists():
                                    downloaded_files.append(Path(p))
                        except Exception as se:
                            logger.warning(f"Error downloading highlight item: {se}")
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

def download_media(url: str, cl=None, max_retries: int = 3, retry_delay: int = 2) -> List[Path]:
    """
    Universal media downloader for Instagram Reels, Posts (photo/video), Carousels (albums), Stories, and Highlights.
    Returns a List of Path objects for all downloaded media items.
    """
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    m_type = detect_media_type(url) or "media"
    logger.info(f"Initiating download for [{m_type.upper()}]: {url}")

    # For Stories and Highlights, instagrapi session is often most reliable
    if m_type in ("story", "highlight") and cl:
        files = _download_via_instagrapi(url, cl)
        if files:
            logger.info(f"Successfully downloaded {len(files)} file(s) via instagrapi for {m_type}.")
            return files

    # Primary engine: yt-dlp
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

    # Secondary engine: fallback to instagrapi if yt-dlp failed
    if cl:
        logger.info("Attempting instagrapi fallback download...")
        files = _download_via_instagrapi(url, cl)
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
