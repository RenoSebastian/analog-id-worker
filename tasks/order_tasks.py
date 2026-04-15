import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from loguru import logger

# Import dari Fase A dan Fase B
from database import get_db_session
from models import Order
from services.api_client import api_client

async def cancel_unpaid_orders_task() -> None:
    """
    Mencari maksimal 50 pesanan 'pending_payment' yang umurnya > 24 jam.
    Mengirimkan instruksi ke Node.js untuk membatalkan pesanan tersebut.
    """
    logger.info("[TASK RUN] Memindai Unpaid Orders (>24 jam)...")
    
    # Menggunakan timezone.utc agar sinkron dengan DateTime(timezone=True) di PostgreSQL
    threshold_time = datetime.now(timezone.utc) - timedelta(hours=24)

    try:
        # Buka sesi database asinkron
        async with get_db_session() as session:
            # ⚡ TACTICAL FIX: Menggunakan FOR UPDATE SKIP LOCKED
            stmt = select(Order.id).where(
                Order.status == 'pending_payment',
                Order.created_at <= threshold_time
            ).with_for_update(skip_locked=True).limit(50) # Batching & Anti-Deadlock

            result = await session.execute(stmt)
            order_ids = result.scalars().all()
            
        # ⚡ PENTING: Blok 'async with' berakhir di sini. Sesi DB ditutup dan Lock dilepas.
        # Ini mencegah Node.js macet saat Worker memanggil API 'trigger_auto_cancel' di bawah.

        if not order_ids:
            logger.debug("Tidak ada Unpaid Orders yang perlu dibatalkan saat ini.")
            return

        logger.info(f"Ditemukan {len(order_ids)} Unpaid Orders. Mulai eksekusi...")

        # Eksekusi per item (Jika 1 gagal, yang lain tetap jalan)
        success_count = 0
        for order_id in order_ids:
            try:
                # Memanggil API Client dari Fase B
                await api_client.trigger_auto_cancel(str(order_id))
                success_count += 1
                logger.success(f"Berhasil mengirim pembatalan untuk Order ID: {order_id}")
            except Exception as e:
                logger.error(f"Gagal mengeksekusi Order ID {order_id}: {str(e)}")
        
        logger.info(f"[TASK DONE] Auto-Cancel selesai. Berhasil: {success_count}/{len(order_ids)}.")

    except Exception as e:
        logger.critical(f"Kesalahan fatal saat query database Unpaid Orders: {str(e)}")


async def auto_complete_shipped_orders_task() -> None:
    """
    Mencari maksimal 50 pesanan 'shipped' yang umurnya > 48 jam sejak terakhir di-update.
    Mengirimkan instruksi ke Node.js untuk merilis dana Escrow secara otomatis.
    """
    logger.info("[TASK RUN] Memindai Shipped Orders (>48 jam)...")
    
    threshold_time = datetime.now(timezone.utc) - timedelta(hours=48)

    try:
        async with get_db_session() as session:
            # ⚡ TACTICAL FIX: Menggunakan FOR UPDATE SKIP LOCKED
            stmt = select(Order.id).where(
                Order.status == 'shipped',
                Order.updated_at <= threshold_time
            ).with_for_update(skip_locked=True).limit(50)

            result = await session.execute(stmt)
            order_ids = result.scalars().all()

        # ⚡ Lock dilepas di sini.

        if not order_ids:
            logger.debug("Tidak ada Shipped Orders yang perlu diselesaikan saat ini.")
            return

        logger.info(f"Ditemukan {len(order_ids)} Shipped Orders. Mulai rilis Escrow...")

        success_count = 0
        for order_id in order_ids:
            try:
                await api_client.trigger_auto_complete(str(order_id))
                success_count += 1
                logger.success(f"Escrow berhasil dirilis untuk Order ID: {order_id}")
            except Exception as e:
                logger.error(f"Gagal merilis Escrow untuk Order ID {order_id}: {str(e)}")
        
        logger.info(f"[TASK DONE] Auto-Complete selesai. Berhasil: {success_count}/{len(order_ids)}.")

    except Exception as e:
        logger.critical(f"Kesalahan fatal saat query database Shipped Orders: {str(e)}")