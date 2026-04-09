import sys
from loguru import logger
from config import settings

def setup_logging() -> None:
    """Mengonfigurasi format dan level logging sentral menggunakan Loguru."""
    logger.remove()  # Menghapus default handler
    logger.add(
        sys.stdout,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level=settings.log_level.upper()
    )
    logger.info("Loguru Logger initialized successfully.")

# Eksekusi langsung saat modul ini di-import pertama kali
setup_logging()