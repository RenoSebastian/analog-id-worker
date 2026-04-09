from contextlib import asynccontextmanager
from fastapi import FastAPI
from loguru import logger

# Import infrastruktur dari fase sebelumnya
from logger import setup_logging
from services.api_client import api_client
from scheduler import setup_scheduler

# Inisialisasi Scheduler
scheduler = setup_scheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manajemen Siklus Hidup (Lifecycle) FastAPI.
    Menangani apa yang terjadi saat server STARTUP dan SHUTDOWN.
    """
    # ==========================================
    # STARTUP SEQUENCE
    # ==========================================
    setup_logging()  # Memastikan format Loguru aktif
    logger.info("⚡ Memulai inisialisasi Analog.id Background Worker...")
    
    # Menyalakan detak jantung (Scheduler)
    scheduler.start()
    logger.success("🫀 Scheduler (Heartbeat) berhasil dihidupkan. Robot sedang memantau...")

    # Memberikan kontrol ke aplikasi FastAPI untuk menerima HTTP Request
    yield

    # ==========================================
    # SHUTDOWN SEQUENCE
    # ==========================================
    logger.warning("🛑 Menerima sinyal shutdown. Mematikan sistem secara elegan...")
    
    # 1. Matikan Scheduler (tunggu job yang sedang jalan selesai)
    scheduler.shutdown(wait=True)
    logger.info("Scheduler berhasil dimatikan.")
    
    # 2. Tutup koneksi API Client (Singleton)
    await api_client.close()
    
    logger.success("Semua proses Worker telah dihentikan dengan aman. Goodbye!")


# Inisialisasi FastAPI App
app = FastAPI(
    title="Analog.id Background Worker",
    description="Asisten Otomatis (Cron Job) untuk ekosistem Analog.id",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/")
async def health_check():
    """Endpoint sederhana untuk memantau status Worker."""
    return {
        "status": "online",
        "message": "Analog.id Worker is Pulsing... 🫀",
        "active_jobs": len(scheduler.get_jobs())
    }