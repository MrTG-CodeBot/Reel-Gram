from pathlib import Path
from typing import Union
from config import logger

def clean_file(filepath: Union[str, Path]) -> None:
    """
    Safely deletes a downloaded file from local storage after processing.
    """
    if not filepath:
        return
    
    try:
        path = Path(filepath)
        if path.exists():
            path.unlink()
            logger.info(f"Cleaned up temporary download: {path}")
        else:
            logger.warning(f"Cleanup requested but file does not exist at: {path}")
    except Exception as e:
        logger.error(f"Error occurred while deleting temporary file {filepath}: {e}")
