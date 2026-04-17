from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from database import AsyncSessionLocal
from models import GradingRequest
from logger import logger

# Asumsi Anda memiliki modul api_client untuk menembak endpoint internal Node.js
# Sesuaikan import ini dengan nama file/fungsi aktual di dalam services/api_client.py Anda
from services import api_client 

async def expire_stale_grading_task():
    """
    Cronjob Task: Mencari tiket Grading yang berstatus MEDIA_READY
    dan tidak di-checkout oleh pembeli dalam waktu 3x24 Jam (72 Jam).
    """
    logger.info("Memulai cronjob: Pengecekan tiket verifikasi premium kedaluwarsa...")
    db: Session = AsyncSessionLocal()
    
    try:
        # Kalkulasi batas waktu (TTL = 3 Hari)
        # Menggunakan timezone-aware datetime agar sinkron dengan PostgreSQL TIMESTAMP WITH TIME ZONE
        threshold_time = datetime.now(timezone.utc) - timedelta(days=3)

        # Query pencarian tiket kedaluwarsa
        # with_for_update(skip_locked=True) memastikan row ini dikunci oleh transaksi saat ini,
        # jika ada worker lain yang mencoba membaca, row ini akan dilewati (skip).
        stale_tickets = db.query(GradingRequest).filter(
            GradingRequest.status == 'MEDIA_READY',
            GradingRequest.updated_at <= threshold_time
        ).with_for_update(skip_locked=True).all()

        if not stale_tickets:
            logger.debug("Tidak ada tiket grading yang melewati batas 3x24 jam saat ini.")
            return

        logger.info(f"Ditemukan {len(stale_tickets)} tiket grading yang harus dihanguskan (EXPIRED).")

        for ticket in stale_tickets:
            try:
                # Pendelegasian aksi ke Backend Node.js Utama.
                # Kita tembak endpoint internal agar Node.js yang melakukan update ke database
                # karena Node.js mungkin perlu mengirimkan Notifikasi/Email ke Penjual & Pembeli.
                endpoint_url = f"/api/internal/grading/{ticket.id}/expire"
                
                # Asumsi api_client memiliki metode post_internal untuk request service-to-service
                response = await api_client.post_internal(endpoint_url, {})

                if response and response.get("success"):
                    logger.info(f"Berhasil menginstruksikan Node.js untuk expire tiket {ticket.id}")
                else:
                    logger.error(f"Node.js gagal memproses expire tiket {ticket.id}: {response}")

            except Exception as req_error:
                logger.error(f"Gagal mengirim request internal untuk tiket {ticket.id}: {str(req_error)}")

    except Exception as e:
        logger.error(f"Kegagalan sistem pada task expire_stale_grading_task: {str(e)}")
    finally:
        db.close()
        logger.info("Selesai eksekusi cronjob grading.")