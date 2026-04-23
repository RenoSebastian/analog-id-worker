import logging
import uuid
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_
import redis.asyncio as redis 

from database import AsyncSessionLocal
from models import Auction, AuctionBid, Order 
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
    async with AsyncSessionLocal() as db:
        try:
            now = _get_current_time()

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
                
                final_start_price = float(auction.current_price) if auction.current_price else 0.0

                # PERBAIKAN TAHAP 2: Inisialisasi State Awal dan Pembersihan Data Kotor
                await redis_client.set(f"auction:{auction_id}:price", final_start_price)
                await redis_client.delete(f"auction:{auction_id}:freeze")
                await redis_client.delete(f"auction:{auction_id}:leaderboard") # Hapus ZSET lama
                await redis_client.delete(f"auction:{auction_id}:history")     # Hapus List history lama

                auction.status = 'ACTIVE'
                
                logger.info(f"[START] Lelang {auction_id} diaktifkan. Redis state terinisialisasi di harga Rp{final_start_price}.")
            
            if auctions_to_start:
                await db.commit() 

        except Exception as e:
            await db.rollback() 
            logger.error(f"[START ERROR] Terjadi kesalahan saat mengaktifkan lelang: {str(e)}")


async def task_freeze_nearing_auctions():
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
                freeze_key = f"auction:{auction.id}:freeze"
                await redis_client.set(freeze_key, '1')
                auction.status = 'FREEZE'
                
                logger.info(f"[FREEZE] Lelang {auction.id} dikunci 15 detik sebelum berakhir.")
            
            if auctions_to_freeze:
                await db.commit() 

        except Exception as e:
            await db.rollback() 
            logger.error(f"[FREEZE ERROR] Terjadi kesalahan: {str(e)}")


async def task_evaluate_winners():
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
                
                # PERBAIKAN TAHAP 2: Ekstraksi Pemenang Mutlak dari ZSET Leaderboard
                # Mengambil peringkat 1 (index 0 ke 0) beserta nilainya
                top_bidder_data = await redis_client.zrevrange(
                    f"auction:{auction_id}:leaderboard", 0, 0, withscores=True
                )

                winner_id = None
                final_price = 0.0

                if top_bidder_data:
                    # ZREVRANGE withscores mengembalikan tuple [(member, score)]
                    winner_id = top_bidder_data[0][0]
                    final_price = float(top_bidder_data[0][1])

                auction.status = 'EVALUATION'
                await db.flush() 

                if not winner_id:
                    auction.status = 'FAILED'
                    logger.info(f"[EVALUATION] Lelang {auction_id} GAGAL (Tidak ada bid di leaderboard).")
                else:
                    auction.winner_id = winner_id
                    auction.current_price = final_price
                    auction.status = 'COMPLETED'

                    # Sinkronisasi state memori pemenang ke persisten DB (Jika belum masuk DB)
                    bid_stmt = select(AuctionBid).where(
                        and_(
                            AuctionBid.auction_id == auction_id,
                            AuctionBid.user_id == winner_id,
                            AuctionBid.bid_amount == final_price
                        )
                    )
                    bid_result = await db.execute(bid_stmt)
                    winning_bid = bid_result.scalars().first()

                    # Jika sistem belum mencatat log bid tertinggi ini ke tabel (karena micro-transactions hanya di Redis), buat record-nya
                    if not winning_bid:
                        winning_bid = AuctionBid(
                            id=uuid.uuid4(),
                            auction_id=auction_id,
                            user_id=winner_id,
                            bid_amount=final_price,
                            status='WINNER'
                        )
                        db.add(winning_bid)
                    else:
                        winning_bid.status = 'WINNER'

                    # Pembuatan Order Otomatis
                    new_order = Order(
                        id=uuid.uuid4(),
                        auction_id=auction_id,
                        buyer_id=winner_id,
                        store_id=auction.store_id, 
                        subtotal=final_price,
                        shipping_fee=0, 
                        grading_fee=0,
                        grand_total=final_price,
                        status='pending_payment',
                        shipping_address="ALAMAT_BELUM_DIPILIH" 
                    )
                    db.add(new_order)
                    
                    logger.info(f"[EVALUATION] Lelang {auction_id} SELESAI. Pemenang Mutlak: {winner_id} - Rp{final_price}")

                # Pembersihan seluruh Memory Space milik lelang ini (Garbage Collection)
                keys_to_delete = await redis_client.keys(f"auction:{auction_id}:*")
                if keys_to_delete:
                    await redis_client.delete(*keys_to_delete)

            if evaluations:
                await db.commit()

        except Exception as e:
            await db.rollback()
            logger.error(f"[EVAL_ERROR] Gagal mengevaluasi pemenang: {str(e)}")


async def task_runner_up_handover():
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

                order.status = 'cancelled'
                logger.info(f"[SLA_BREACH] Order {order.id} dibatalkan karena melebihi 24 jam pembayaran.")

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

                    new_order = Order(
                        id=uuid.uuid4(),
                        auction_id=auction_id,
                        buyer_id=runner_up_bid.user_id,
                        store_id=auction.store_id,
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
                    logger.info(f"[HANDOVER] Lelang {auction_id} GAGAL KESELURUHAN (Tidak ada runner up).")

            if expired_orders:
                await db.commit()

        except Exception as e:
            await db.rollback()
            logger.error(f"[SLA_ERROR] Terjadi kesalahan saat Handover: {str(e)}")