"""
Cleanup utilities for safely removing temporary downloaded media files.
"""

from pathlib import Path
from typing import Union, List
from config import logger

def clean_file(filepath: Union[str, Path, List[Path], List[str]]) -> None:
    """
    Safely removes downloaded files from local storage after Telegram upload.
    Accepts a single path or an iterable of paths.
    """
    if not filepath:
        return

    if isinstance(filepath, (list, tuple, set)):
        for f in filepath:
            clean_file(f)
        return

    try:
        path = Path(filepath)
        if path.exists():
            path.unlink()
            logger.info(f"Removed temporary file: {path.name}")
    except Exception as e:
        logger.error(f"Failed to remove temporary file {filepath}: {e}")
