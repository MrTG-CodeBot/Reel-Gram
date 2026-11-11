from pathlib import Path
from typing import Union, List
from config import logger

def clean_file(filepath: Union[str, Path, List[Path], List[str]]) -> None:
    """
    Safely deletes downloaded file(s) from local storage after processing.
    Accepts a single Path/str or a list of Paths/strings.
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
            logger.info(f"Cleaned up temporary download: {path}")
        else:
            logger.debug(f"Cleanup requested but file does not exist at: {path}")
    except Exception as e:
        logger.error(f"Error occurred while deleting temporary file {filepath}: {e}")
