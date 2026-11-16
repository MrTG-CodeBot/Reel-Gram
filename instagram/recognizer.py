"""
Song recognition module.
Identifies music tracks from Instagram video/audio clips using acoustic fingerprinting
(Shazam) and Instagram native music metadata.
"""

import asyncio
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any
from shazamio import Shazam
from config import DOWNLOAD_DIR, logger
from downloader.download import get_ffmpeg_executable


def extract_audio_slice(input_path: Path, duration_seconds: int = 10) -> Optional[Path]:
    """
    Extracts a short MP3 audio snippet from a video or audio file for song fingerprinting.
    """
    ffmpeg_exe = get_ffmpeg_executable()
    if not ffmpeg_exe or not input_path.exists():
        return None

    slice_name = f"slice_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp3"
    slice_path = DOWNLOAD_DIR / slice_name

    cmd = [
        ffmpeg_exe,
        "-y",
        "-ss", "0",
        "-t", str(duration_seconds),
        "-i", str(input_path),
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        str(slice_path)
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        if slice_path.exists() and slice_path.stat().st_size > 0:
            return slice_path
    except Exception as e:
        logger.debug(f"Could not extract audio slice: {e}")

    return None


async def identify_song_from_file(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Asynchronously identifies a song from an audio or video file using Shazam.
    Returns song title, artist, album, cover art URL, and genres.
    """
    if not file_path or not file_path.exists():
        return None

    # Use a small audio slice for fastest recognition
    slice_path = extract_audio_slice(file_path, duration_seconds=12)
    target_path = slice_path or file_path

    try:
        shazam = Shazam()
        data = await shazam.recognize(str(target_path))

        track = data.get("track")
        if not track:
            return None

        title = track.get("title") or "Unknown Title"
        artist = track.get("subtitle") or "Unknown Artist"

        images = track.get("images") or {}
        cover_url = images.get("coverarthq") or images.get("coverart")

        album = None
        sections = track.get("sections") or []
        for s in sections:
            if s.get("type") == "SONG":
                for item in s.get("metadata", []):
                    if item.get("title", "").lower() == "album":
                        album = item.get("text")
                        break

        genre = track.get("genres", {}).get("primary")

        logger.info(f"Song identified: '{title}' by '{artist}' (Album: {album})")
        return {
            "title": title,
            "artist": artist,
            "album": album,
            "genre": genre,
            "cover_url": cover_url,
            "shazam_url": track.get("url")
        }

    except Exception as e:
        logger.warning(f"Shazam recognition error: {e}")
        return None

    finally:
        if slice_path and slice_path.exists():
            try:
                slice_path.unlink()
            except Exception:
                pass


def identify_song_sync(file_path: Path) -> Optional[Dict[str, Any]]:
    """Synchronous wrapper for identify_song_from_file."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, identify_song_from_file(file_path))
            return future.result()
    else:
        return loop.run_until_complete(identify_song_from_file(file_path))
