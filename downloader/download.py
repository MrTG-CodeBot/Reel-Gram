import time
from pathlib import Path
from typing import Optional
import yt_dlp
from config import DOWNLOAD_DIR, logger

def progress_hook(d: dict) -> None:
    """
    Callback progress hook for yt-dlp to report download progress.
    """
    if d.get("status") == "downloading":
        downloaded = d.get("downloaded_bytes", 0)
        total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
        percent = (downloaded / total * 100) if total > 0 else 0
        speed = d.get("speed", 0)
        speed_mb = (speed / 1024 / 1024) if speed else 0
        logger.info(f"Downloading Reel... {percent:.1f}% | Speed: {speed_mb:.2f} MB/s")
    elif d.get("status") == "finished":
        logger.info("Reel download complete. Post-processing file...")

def download_reel(url: str, max_retries: int = 3, retry_delay: int = 2) -> Optional[Path]:
    """
    Downloads an Instagram Reel using yt-dlp to the downloads directory.
    Returns the file Path upon success, or raises an exception/returns None on failure.
    """
    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": str(DOWNLOAD_DIR / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
        "merge_output_format": "mp4",
        "noplaylist": True,
        "socket_timeout": 30,
    }

    logger.info(f"Downloading Reel from URL: {url}")

    for attempt in range(1, max_retries + 1):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                # Due to merging/post-processing, extension might have changed (e.g. from ydl_opts)
                # Prepare filename handles the formatting, but let's check for exact path existance.
                filepath = Path(filename)
                
                # If the exact extension didn't match (e.g. merged to mp4 from webm/m4a), check the dir
                if not filepath.exists():
                    video_id = info.get("id")
                    if video_id:
                        for child in DOWNLOAD_DIR.iterdir():
                            if child.name.startswith(video_id) and child.suffix in [".mp4", ".mkv", ".webm"]:
                                filepath = child
                                break

                if filepath.exists():
                    logger.info(f"Reel successfully downloaded to: {filepath} (Size: {filepath.stat().st_size} bytes)")
                    return filepath
                else:
                    raise FileNotFoundError(f"yt-dlp completed download but output file wasn't found at: {filepath}")

        except yt_dlp.utils.DownloadError as e:
            err_msg = str(e)
            logger.warning(f"Download attempt {attempt}/{max_retries} failed. Error: {err_msg}")
            
            # Detect permanent (non-retryable) failures
            lower_err = err_msg.lower()
            if any(term in lower_err for term in ["private", "login", "404", "does not exist", "removed"]):
                logger.error("Non-retryable error detected. Skipping further download attempts.")
                raise ValueError(f"Instagram Reel is inaccessible (private, deleted, or login-required): {err_msg}") from e

            if attempt < max_retries:
                time.sleep(retry_delay)
            else:
                logger.error(f"Download failed after {max_retries} attempts.")
                raise
        except Exception as e:
            logger.error(f"Unexpected error during yt-dlp download: {e}")
            if attempt < max_retries:
                time.sleep(retry_delay)
            else:
                raise
    return None
