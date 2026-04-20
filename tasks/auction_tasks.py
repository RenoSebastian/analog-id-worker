import logging
import uuid
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_
import redis.asyncio as redis 

from database import AsyncSessionLocal
from models import Auction, AuctionBid, Product, Order 
from config import settings 

# Inisialisasi Logger
logger = logging.getLogger("AuctionWorkerTask")

# Redis Asyncio Client
redis_client = redis.from_url(
    settings.redis_url, 
    decode_responses=True
)

def _get_current_time():
    """Helper untuk mock/testing waktu"""
    return datetime.now()

async def task_start_scheduled_auctions():
    """
    Cron: Berjalan setiap detik / menit.
    Mencari lelang berstatus SCHEDULED yang start_time-nya sudah tercapai.
    Mengubah status menjadi ACTIVE dan menginisialisasi state dasar di Redis.
    """
    async with AsyncSessionLocal() as db:
        try:
            now = _get_current_time()

            # Mencari lelang yang sudah waktunya dimulai
            stmt = select(Auction).where(
                and_(
                    Auction.status == 'SCHEDULED',
                    Auction.start_time <= now
                )
            )
            result = await db.execute(stmt)
            auctions_to_start = result.scalars().all()

            for auction in auctions_to_start:
                auction_id = str(auction.id)
                # Pastikan menggunakan start_price atau current_price sebagai pijakan awal
                start_price = float(auction.current_price or auction.start_price)

                # 1. Inisialisasi State di Redis Memory
                # Harus sinkron dengan kebutuhan LUA Script di Node.js
                await redis_client.set(f"auction:{auction_id}:price", start_price)
                await redis_client.delete(f"auction:{auction_id}:winner")
                await redis_client.delete(f"auction:{auction_id}:freeze")

                # 2. Update status Postgres menjadi ACTIVE
                auction.status = 'ACTIVE'
                
                logger.info(f"[START] Lelang {auction_id} diaktifkan. Redis state terinisialisasi di harga Rp{start_price}.")
            
            if auctions_to_start:
                await db.commit() 

        except Exception as e:
            await db.rollback() 
            logger.error(f"[START ERROR] Terjadi kesalahan saat mengaktifkan lelang: {str(e)}")

async def task_freeze_nearing_auctions():
    """
    Cron: Berjalan setiap detik / 5 detik.
    Mencari lelang yang waktu end_time-nya tersisa <= 15 detik.
    Mengunci (Freeze) di Redis agar Socket.io Node.js menolak bid baru.
    """
    async with AsyncSessionLocal() as db:
        try:
            now = _get_current_time()
            freeze_threshold = now + timedelta(seconds=15)

            stmt = select(Auction).where(
                and_(
                    Auction.status == 'ACTIVE',
                    Auction.end_time <= freeze_threshold
                )
            )
            result = await db.execute(stmt)
            auctions_to_freeze = result.scalars().all()

            for auction in auctions_to_freeze:
                # 1. Kunci State di Redis 
                freeze_key = f"auction:{auction.id}:freeze"
                await redis_client.set(freeze_key, '1')

                # 2. Update status Postgres
                auction.status = 'FREEZE'
                
                logger.info(f"[FREEZE] Lelang {auction.id} dikunci 15 detik sebelum berakhir.")
            
            if auctions_to_freeze:
                await db.commit() 

        except Exception as e:
            await db.rollback() 
            logger.error(f"[FREEZE ERROR] Terjadi kesalahan: {str(e)}")


async def task_evaluate_winners():
    """
    Cron: Berjalan setiap menit.
    Mengevaluasi lelang yang berstatus FREEZE dan waktunya sudah habis.
    Menarik data pemenang dari Redis, membuat Order, dan sinkronisasi ke Postgres.
    """
    async with AsyncSessionLocal() as db:
        try:
            now = _get_current_time()

            stmt = select(Auction).where(
                and_(
                    Auction.status == 'FREEZE',
                    Auction.end_time <= now
                )
            )
            result = await db.execute(stmt)
            evaluations = result.scalars().all()

            for auction in evaluations:
                auction_id = str(auction.id)
                
                # 1. Tarik Data Final dari Redis Memory
                final_price = await redis_client.get(f"auction:{auction_id}:price")
                winner_id = await redis_client.get(f"auction:{auction_id}:winner")

                # Update status awal ke EVALUATION untuk mencegah double-processing
                auction.status = 'EVALUATION'
                await db.flush() 

                if not winner_id:
                    auction.status = 'FAILED'
                    
                    prod_stmt = select(Product).where(Product.id == auction.product_id)
                    prod_result = await db.execute(prod_stmt)
                    product = prod_result.scalars().first()
                    
                    if product:
                        product.is_locked = False
                    
                    logger.info(f"[EVALUATION] Lelang {auction_id} GAGAL (Tidak ada bid). Produk di-unlock.")
                else:
                    final_price = float(final_price)
                    auction.winner_id = winner_id
                    auction.current_price = final_price
                    auction.status = 'COMPLETED'

                    # Cari winning bid
                    bid_stmt = select(AuctionBid).where(
                        and_(
                            AuctionBid.auction_id == auction_id,
                            AuctionBid.user_id == winner_id,
                            AuctionBid.bid_amount == final_price
                        )
                    )
                    bid_result = await db.execute(bid_stmt)
                    winning_bid = bid_result.scalars().first()

                    if winning_bid:
                        winning_bid.status = 'WINNER'

                    # Ambil produk untuk store_id
                    prod_stmt = select(Product).where(Product.id == auction.product_id)
                    prod_result = await db.execute(prod_stmt)
                    product = prod_result.scalars().first()
                    
                    new_order = Order(
                        id=uuid.uuid4(),
                        auction_id=auction_id,
                        buyer_id=winner_id,
                        store_id=product.store_id,
                        subtotal=final_price,
                        shipping_fee=0, 
                        grading_fee=0,
                        grand_total=final_price,
                        status='pending_payment',
                        shipping_address="ALAMAT_BELUM_DIPILIH" 
                    )
                    db.add(new_order)
                    
                    logger.info(f"[EVALUATION] Lelang {auction_id} SELESAI. Pemenang: {winner_id} - Rp{final_price}")

                # 2. Cleanup Redis Memory 
                keys_to_delete = await redis_client.keys(f"auction:{auction_id}:*")
                if keys_to_delete:
                    await redis_client.delete(*keys_to_delete)

            if evaluations:
                await db.commit()

        except Exception as e:
            await db.rollback()
            logger.error(f"[EVAL_ERROR] Gagal mengevaluasi pemenang: {str(e)}")


async def task_runner_up_handover():
    """
    Cron: Berjalan setiap 5 menit (SLA Monitor).
    Mencari Order lelang yang berstatus 'pending_payment' lebih dari 24 jam.
    Membatalkan order tersebut dan mengalihkan hak ke Bidder tertinggi kedua (Runner Up).
    """
    async with AsyncSessionLocal() as db:
        try:
            sla_limit = _get_current_time() - timedelta(hours=24)

            stmt = select(Order).where(
                and_(
                    Order.auction_id.isnot(None),
                    Order.status == 'pending_payment',
                    Order.created_at <= sla_limit
                )
            )
            result = await db.execute(stmt)
            expired_orders = result.scalars().all()

            for order in expired_orders:
                auction_id = order.auction_id
                
                auc_stmt = select(Auction).where(Auction.id == auction_id)
                auc_result = await db.execute(auc_stmt)
                auction = auc_result.scalars().first()

                # 1. Batalkan Order Pemenang Pertama
                order.status = 'cancelled'
                logger.info(f"[SLA_BREACH] Order {order.id} dibatalkan karena melebihi 24 jam pembayaran.")

                # 2. Cari Runner Up
                bid_stmt = select(AuctionBid).where(
                    and_(
                        AuctionBid.auction_id == auction_id,
                        AuctionBid.user_id != auction.winner_id,
                        AuctionBid.status == 'VALID'
                    )
                ).order_by(AuctionBid.bid_amount.desc())
                
                bid_result = await db.execute(bid_stmt)
                runner_up_bid = bid_result.scalars().first()

                if runner_up_bid:
                    auction.status = 'HANDOVER_TO_RUNNER_UP'
                    auction.winner_id = runner_up_bid.user_id
                    auction.current_price = runner_up_bid.bid_amount
                    
                    runner_up_bid.status = 'RUNNER_UP'

                    prod_stmt = select(Product).where(Product.id == auction.product_id)
                    prod_result = await db.execute(prod_stmt)
                    product = prod_result.scalars().first()
                    
                    new_order = Order(
                        id=uuid.uuid4(),
                        auction_id=auction_id,
                        buyer_id=runner_up_bid.user_id,
                        store_id=product.store_id,
                        subtotal=runner_up_bid.bid_amount,
                        shipping_fee=0,
                        grading_fee=0,
                        grand_total=runner_up_bid.bid_amount,
                        status='pending_payment',
                        shipping_address="ALAMAT_BELUM_DIPILIH"
                    )
                    db.add(new_order)
                    logger.info(f"[HANDOVER] Lelang {auction_id} dialihkan ke Runner Up: {runner_up_bid.user_id}")
                else:
                    auction.status = 'FAILED'
                    
                    prod_stmt = select(Product).where(Product.id == auction.product_id)
                    prod_result = await db.execute(prod_stmt)
                    product = prod_result.scalars().first()
                    
                    if product:
                        product.is_locked = False
                    logger.info(f"[HANDOVER] Lelang {auction_id} GAGAL KESELURUHAN (Tidak ada runner up).")

            if expired_orders:
                await db.commit()

        except Exception as e:
            await db.rollback()
            logger.error(f"[SLA_ERROR] Terjadi kesalahan saat Handover: {str(e)}")