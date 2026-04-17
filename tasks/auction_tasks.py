import logging
import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_
import redis

from database import SessionLocal
# Asumsi model SQLAlchemy Anda sudah disinkronisasi dengan skema Postgres fase 1
from models import Auction, AuctionBid, Product, Order, User

from config import settings # Asumsi Anda memiliki modul config untuk env vars

# Inisialisasi Logger
logger = logging.getLogger("AuctionWorkerTask")

# Inisialisasi Redis Client (Shared State dengan Node.js)
redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    password=settings.REDIS_PASSWORD,
    decode_responses=True
)

def _get_current_time():
    """Helper untuk mock/testing waktu"""
    return datetime.utcnow()

def task_freeze_nearing_auctions():
    """
    Cron: Berjalan setiap detik / 5 detik.
    Mencari lelang yang waktu end_time-nya tersisa <= 15 detik.
    Mengunci (Freeze) di Redis agar Socket.io Node.js menolak bid baru.
    """
    db: Session = SessionLocal()
    try:
        now = _get_current_time()
        freeze_threshold = now + timedelta(seconds=15)

        # Mencari lelang yang masih ACTIVE dan akan segera berakhir
        auctions_to_freeze = db.query(Auction).filter(
            Auction.status == 'ACTIVE',
            Auction.end_time <= freeze_threshold
        ).all()

        for auction in auctions_to_freeze:
            # 1. Kunci State di Redis (Atomic Operation)
            freeze_key = f"auction:{auction.id}:freeze"
            redis_client.set(freeze_key, '1')

            # 2. Update status Postgres
            auction.status = 'FREEZE'
            
            logger.info(f"[FREEZE] Lelang {auction.id} dikunci 15 detik sebelum berakhir.")
        
        if auctions_to_freeze:
            db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"[FREEZE ERROR] Terjadi kesalahan: {str(e)}")
    finally:
        db.close()


def task_evaluate_winners():
    """
    Cron: Berjalan setiap menit.
    Mengevaluasi lelang yang berstatus FREEZE dan waktunya sudah habis.
    Menarik data pemenang dari Redis, membuat Order, dan sinkronisasi ke Postgres.
    """
    db: Session = SessionLocal()
    try:
        now = _get_current_time()

        evaluations = db.query(Auction).filter(
            Auction.status == 'FREEZE',
            Auction.end_time <= now
        ).all()

        for auction in evaluations:
            auction_id = str(auction.id)
            
            # 1. Tarik Data Final dari Redis Memory
            final_price = redis_client.get(f"auction:{auction_id}:price")
            winner_id = redis_client.get(f"auction:{auction_id}:winner")

            # Update status awal ke EVALUATION untuk mencegah double-processing
            auction.status = 'EVALUATION'
            db.commit()

            if not winner_id:
                # Skenario: Tidak ada satupun yang melakukan bid
                auction.status = 'FAILED'
                
                # Buka kembali kunci produk agar bisa di-checkout reguler
                product = db.query(Product).filter(Product.id == auction.product_id).first()
                if product:
                    product.is_locked = False
                
                logger.info(f"[EVALUATION] Lelang {auction_id} GAGAL (Tidak ada bid). Produk di-unlock.")
            else:
                # Skenario: Ada pemenang.
                final_price = float(final_price)
                auction.winner_id = winner_id
                auction.current_price = final_price
                auction.status = 'COMPLETED'

                # Tandai flag WINNER di Audit Log (Jika Anda menggunakan Write-Behind log)
                winning_bid = db.query(AuctionBid).filter(
                    AuctionBid.auction_id == auction_id,
                    AuctionBid.user_id == winner_id,
                    AuctionBid.bid_amount == final_price
                ).first()

                if winning_bid:
                    winning_bid.status = 'WINNER'

                # Auto-Generate Order System (SLA Pembayaran 24 Jam dimulai)
                product = db.query(Product).filter(Product.id == auction.product_id).first()
                
                new_order = Order(
                    id=uuid.uuid4(),
                    auction_id=auction_id,
                    buyer_id=winner_id,
                    store_id=product.store_id,
                    subtotal=final_price,
                    shipping_fee=0, # Akan di-update saat buyer memilih kurir di halaman pembayaran
                    grading_fee=0,
                    grand_total=final_price, # Sementara grand_total == subtotal
                    status='pending_payment',
                    shipping_address="ALAMAT_BELUM_DIPILIH" # Placeholder
                )
                db.add(new_order)
                
                logger.info(f"[EVALUATION] Lelang {auction_id} SELESAI. Pemenang: {winner_id} - Rp{final_price}")

            # 2. Cleanup Redis Memory (Garbage Collection)
            keys_to_delete = redis_client.keys(f"auction:{auction_id}:*")
            if keys_to_delete:
                redis_client.delete(*keys_to_delete)

        db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"[EVAL_ERROR] Gagal mengevaluasi pemenang: {str(e)}")
    finally:
        db.close()


def task_runner_up_handover():
    """
    Cron: Berjalan setiap 5 menit (SLA Monitor).
    Mencari Order lelang yang berstatus 'pending_payment' lebih dari 24 jam.
    Membatalkan order tersebut dan mengalihkan hak ke Bidder tertinggi kedua (Runner Up).
    """
    db: Session = SessionLocal()
    try:
        sla_limit = _get_current_time() - timedelta(hours=24)

        expired_orders = db.query(Order).filter(
            Order.auction_id.isnot(None),
            Order.status == 'pending_payment',
            Order.created_at <= sla_limit
        ).all()

        for order in expired_orders:
            auction_id = order.auction_id
            auction = db.query(Auction).filter(Auction.id == auction_id).first()

            # 1. Batalkan Order Pemenang Pertama
            order.status = 'cancelled'
            logger.info(f"[SLA_BREACH] Order {order.id} dibatalkan karena melebihi 24 jam pembayaran.")

            # 2. Cari Runner Up di Tabel Histori Bid
            # Mencari bid tertinggi di bawah harga pemenang pertama
            runner_up_bid = db.query(AuctionBid).filter(
                AuctionBid.auction_id == auction_id,
                AuctionBid.user_id != auction.winner_id, # Bukan user yang gagal bayar
                AuctionBid.status == 'VALID'
            ).order_by(AuctionBid.bid_amount.desc()).first()

            if runner_up_bid:
                # Transisi status lelang
                auction.status = 'HANDOVER_TO_RUNNER_UP'
                auction.winner_id = runner_up_bid.user_id
                auction.current_price = runner_up_bid.bid_amount
                
                runner_up_bid.status = 'RUNNER_UP'

                # Buat Order Baru untuk Runner Up (Waktu 24 Jam di-reset)
                product = db.query(Product).filter(Product.id == auction.product_id).first()
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
                # Jika tidak ada Runner Up (Misal hanya ada 1 bidder, dan dia gagal bayar)
                auction.status = 'FAILED'
                product = db.query(Product).filter(Product.id == auction.product_id).first()
                if product:
                    product.is_locked = False
                logger.info(f"[HANDOVER] Lelang {auction_id} GAGAL KESELURUHAN (Tidak ada runner up).")

        if expired_orders:
            db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"[SLA_ERROR] Terjadi kesalahan saat Handover: {str(e)}")
    finally:
        db.close()