import logging
from pathlib import Path
import config

def configure_logging():
    Path(config.LOGS_DIR).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(Path(config.LOGS_DIR) / "jarvis.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
