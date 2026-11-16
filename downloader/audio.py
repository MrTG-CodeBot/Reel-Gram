"""
Audio extraction, format conversion, and tagging utilities.
Extracts audio tracks from video files using FFmpeg, downloads full songs via yt-dlp,
and embeds metadata and album artwork tags.
"""

import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List
import yt_dlp
from config import DOWNLOAD_DIR, logger
from downloader.download import get_ffmpeg_executable

FORMAT_EXTENSIONS = {
    "mp3": ".mp3",
    "m4a": ".m4a",
    "wav": ".wav",
    "flac": ".flac",
    "ogg": ".ogg",
}


def extract_audio_from_video(
    video_path: Path,
    output_format: str = "mp3",
    title: Optional[str] = None,
    artist: Optional[str] = None,
    thumbnail_path: Optional[Path] = None
) -> Optional[Path]:
    """
    Extracts audio from a local video file using FFmpeg.
    Supports mp3, m4a, wav, flac, and ogg formats, and embeds metadata.
    """
    ffmpeg_exe = get_ffmpeg_executable()
    if not ffmpeg_exe:
        logger.error("FFmpeg not available for audio extraction.")
        return None

    fmt = output_format.lower().strip()
    ext = FORMAT_EXTENSIONS.get(fmt, ".mp3")
    output_name = f"audio_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
    output_path = DOWNLOAD_DIR / output_name

    cmd = [ffmpeg_exe, "-y", "-i", str(video_path), "-vn"]

    if fmt == "mp3":
        cmd.extend(["-c:a", "libmp3lame", "-b:a", "256k"])
    elif fmt == "m4a":
        # First attempt stream copy, fallback to aac re-encoding if needed
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    elif fmt == "flac":
        cmd.extend(["-c:a", "flac"])
    elif fmt == "wav":
        cmd.extend(["-c:a", "pcm_s16le"])
    elif fmt == "ogg":
        cmd.extend(["-c:a", "libopus", "-b:a", "128k"])
    else:
        cmd.extend(["-c:a", "libmp3lame", "-b:a", "256k"])

    if title:
        cmd.extend(["-metadata", f"title={title}"])
    if artist:
        cmd.extend(["-metadata", f"artist={artist}"])

    cmd.append(str(output_path))

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        if output_path.exists() and output_path.stat().st_size > 0:
            logger.info(f"Audio extracted successfully: {output_path.name}")
            
            # Embed cover art if thumbnail is available
            if thumbnail_path and thumbnail_path.exists() and fmt in ("mp3", "m4a"):
                _embed_artwork(output_path, thumbnail_path, fmt)

            return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg audio extraction failed: {e.stderr.decode('utf-8', errors='ignore')[:200]}")
    except Exception as e:
        logger.error(f"Unexpected error during audio extraction: {e}")

    return None


def _generate_search_candidates(query: str) -> List[str]:
    """
    Generates an ordered list of search queries across YouTube and SoundCloud
    with intelligent noise removal to ensure maximum track discovery.
    """
    clean = re.sub(r"\s*-\s*(Single|EP|Album|Audio)\b", "", query, flags=re.I).strip()
    candidates = []

    # 1. Primary searches on YouTube
    candidates.append(f"ytsearch3:{clean} audio")
    candidates.append(f"ytsearch3:{clean}")

    # 2. Inverted search: "Title Artist" if formatted as "Artist - Title"
    if " - " in clean:
        parts = clean.split(" - ", 1)
        artist_part = parts[0].strip()
        title_part = parts[1].strip()
        candidates.append(f"ytsearch3:{title_part} {artist_part}")

    # 3. SoundCloud fallback
    candidates.append(f"scsearch1:{clean}")

    # 4. Simplified query stripping parenthetical modifiers (e.g. remix/female version)
    no_parens = re.sub(r"[\(\[].*?[\)\]]", "", clean).strip()
    if no_parens and no_parens != clean:
        candidates.append(f"ytsearch3:{no_parens}")
        candidates.append(f"scsearch1:{no_parens}")

    # Deduplicate while preserving priority order
    seen = set()
    result = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)

    return result


def download_full_song_by_query(
    query: str,
    output_format: str = "mp3"
) -> Optional[Dict[str, Any]]:
    """
    Searches and downloads the full song via yt-dlp across YouTube and SoundCloud.
    Iterates through prioritized search candidates until a track is found and downloaded.
    Returns a dictionary containing the downloaded file path and track metadata.
    """
    fmt = output_format.lower().strip()
    if fmt not in FORMAT_EXTENSIONS:
        fmt = "mp3"

    ffmpeg_exe = get_ffmpeg_executable()
    candidates = _generate_search_candidates(query)

    unique_id = f"song_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    out_tmpl = str(DOWNLOAD_DIR / f"{unique_id}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_tmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": fmt if fmt != "m4a" else "m4a",
                "preferredquality": "256",
            },
            {
                "key": "FFmpegMetadata",
                "add_metadata": True,
            }
        ],
    }

    if ffmpeg_exe:
        ydl_opts["ffmpeg_location"] = ffmpeg_exe

    search_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    for candidate in candidates:
        logger.info(f"Searching track with candidate: '{candidate}'")
        try:
            # Phase 1: Query metadata first without downloading to pick the single best URL
            with yt_dlp.YoutubeDL(search_opts) as search_ydl:
                info = search_ydl.extract_info(candidate, download=False)
                if not info:
                    continue

                entries = info.get("entries") if "entries" in info else [info]
                entries = [e for e in entries if e]
                if not entries:
                    continue

                entry = entries[0]
                target_url = entry.get("webpage_url") or entry.get("url")
                if not target_url:
                    continue

            # Phase 2: Download ONLY the single selected track
            with yt_dlp.YoutubeDL(ydl_opts) as dl_ydl:
                dl_info = dl_ydl.extract_info(target_url, download=True)
                if not dl_info:
                    continue

                track_title = dl_info.get("track") or dl_info.get("title") or entry.get("title") or query
                artist_name = dl_info.get("artist") or dl_info.get("uploader") or entry.get("uploader") or "Unknown Artist"
                duration = dl_info.get("duration") or entry.get("duration", 0)
                thumbnail_url = dl_info.get("thumbnail") or entry.get("thumbnail")

                expected_file = DOWNLOAD_DIR / f"{unique_id}.{fmt}"
                if not expected_file.exists():
                    for f in DOWNLOAD_DIR.iterdir():
                        if f.name.startswith(unique_id):
                            expected_file = f
                            break

                if expected_file.exists() and expected_file.stat().st_size > 0:
                    logger.info(f"Full song downloaded successfully via '{candidate}': {expected_file.name}")
                    return {
                        "file_path": expected_file,
                        "title": track_title,
                        "artist": artist_name,
                        "duration": int(duration) if duration else 0,
                        "thumbnail_url": thumbnail_url
                    }
        except Exception as e:
            logger.debug(f"Candidate '{candidate}' attempt failed: {e}")
            continue

    logger.warning(f"All search candidates exhausted for query: '{query}'")
    return None


def _embed_artwork(audio_path: Path, thumbnail_path: Path, fmt: str) -> None:
    """Embeds album art into MP3 or M4A files using mutagen."""
    try:
        if fmt == "mp3":
            import mutagen
            from mutagen.mp3 import MP3
            from mutagen.id3 import ID3, APIC, error

            audio = MP3(str(audio_path), ID3=ID3)
            try:
                audio.add_tags()
            except error:
                pass

            with open(thumbnail_path, "rb") as alb:
                audio.tags.add(
                    APIC(
                        encoding=3,
                        mime="image/jpeg",
                        type=3,  # Cover (front)
                        desc="Cover",
                        data=alb.read()
                    )
                )
            audio.save()

        elif fmt == "m4a":
            from mutagen.mp4 import MP4, MP4Cover

            audio = MP4(str(audio_path))
            with open(thumbnail_path, "rb") as alb:
                audio["covr"] = [MP4Cover(alb.read(), imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()
    except Exception as e:
        logger.debug(f"Could not embed artwork into {audio_path.name}: {e}")
