import logging
from datetime import datetime, timedelta
import requests
from sqlalchemy.orm import Session

# Import konfigurasi dan database dari ekosistem worker Anda
import config
from database import AsyncSessionLocal
from models import Dispute, RefundPayout

logger = logging.getLogger(__name__)

# Konfigurasi Header untuk menembus proteksi Internal RPC Bridge Node.js
# Pastikan variabel ini diset di config.py dan .env worker Anda
API_BASE_URL = getattr(config, 'NODE_API_URL', 'http://localhost:5000/api/v1/internal')
HEADERS = {
    "x-api-key": getattr(config, 'INTERNAL_API_KEY', 'your_super_secret_api_key_here'),
    "Content-Type": "application/json"
}

def call_internal_api(endpoint: str, payload: dict = None) -> bool:
    """Helper untuk menembak API Node.js dan mencatat hasilnya."""
    url = f"{API_BASE_URL}{endpoint}"
    try:
        if payload:
            response = requests.post(url, json=payload, headers=HEADERS, timeout=10)
        else:
            response = requests.post(url, headers=HEADERS, timeout=10)
            
        if response.status_code == 200:
            logger.info(f"[SUCCESS] Worker executed {endpoint}")
            return True
        else:
            logger.error(f"[FAILED] Worker execution {endpoint} returned {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"[ERROR] API Call failed for {endpoint}: {str(e)}")
        return False

# =========================================================================
# CASE 1: Auto-Trigger Refund (Admin Inactivity 2x24 Jam)
# =========================================================================
def check_admin_inactivity():
    """Mengecek pesanan retur yang sudah sampai tapi diabaikan penjual/admin."""
    logger.info("Running task: Check Admin Inactivity...")
    db: Session = SessionLocal()
    try:
        threshold_time = datetime.now() - timedelta(hours=48)
        
        # Ambil dispute status 'arrived_at_seller' yang umurnya sudah lewat 48 jam
        stale_disputes = db.query(Dispute).filter(
            Dispute.status == 'arrived_at_seller',
            Dispute.arrived_at < threshold_time
        ).all()

        for dispute in stale_disputes:
            logger.info(f"Dispute {dispute.id} is stale (arrived > 48h). Triggering auto-refund.")
            payload = {
                "resolution": "refund_full",
                "notes": "SYSTEM AUTO-REFUND: Penjual atau Admin tidak melakukan konfirmasi penerimaan barang dalam waktu 2x24 jam sejak barang tiba."
            }
            call_internal_api(f"/disputes/{dispute.id}/auto-resolve", payload)

    finally:
        db.close()


# =========================================================================
# CASE 2: Expired Shipping (Seller Unresponsive 2x24 Jam)
# =========================================================================
def check_seller_unresponsive():
    """Memaksa pesetujuan retur jika penjual diam saja selama 2x24 jam sejak komplain dibuka."""
    logger.info("Running task: Check Seller Unresponsive...")
    db: Session = SessionLocal()
    try:
        threshold_time = datetime.now() - timedelta(hours=48)
        
        unresponsive_disputes = db.query(Dispute).filter(
            Dispute.status == 'open',
            Dispute.created_at < threshold_time
        ).all()

        for dispute in unresponsive_disputes:
            logger.info(f"Dispute {dispute.id} ignored by seller (> 48h). Forcing return acceptance.")
            call_internal_api(f"/disputes/{dispute.id}/auto-accept-return")

    finally:
        db.close()


# =========================================================================
# CASE 3: Buyer No-Response (Tidak Input Resi 3x24 Jam)
# =========================================================================
def check_buyer_no_response():
    """Membatalkan komplain jika pembeli malas/lupa menginput resi pengembalian."""
    logger.info("Running task: Check Buyer No-Response...")
    db: Session = SessionLocal()
    try:
        threshold_time = datetime.now() - timedelta(hours=72)
        
        lazy_buyers = db.query(Dispute).filter(
            Dispute.status == 'returning',
            Dispute.return_tracking_number.is_(None),
            Dispute.accepted_at < threshold_time
        ).all()

        for dispute in lazy_buyers:
            logger.info(f"Dispute {dispute.id} missing resi (> 72h). Triggering rejection.")
            payload = {
                "resolution": "reject_buyer",
                "notes": "SYSTEM AUTO-REJECT: Pembeli gagal menyerahkan nomor resi pengiriman retur dalam waktu 3x24 jam. Dana diteruskan ke Penjual."
            }
            call_internal_api(f"/disputes/{dispute.id}/auto-resolve", payload)

    finally:
        db.close()


# =========================================================================
# CASE 4: Automatic Fund Release (Deadlock Mediasi 7 Hari)
# =========================================================================
def check_mediation_deadlock():
    """Mengakhiri mediasi buntu yang sudah memakan waktu 7 hari."""
    logger.info("Running task: Check Mediation Deadlock...")
    db: Session = SessionLocal()
    try:
        threshold_time = datetime.now() - timedelta(days=7)
        
        deadlocks = db.query(Dispute).filter(
            Dispute.status == 'mediation',
            Dispute.mediation_start_at < threshold_time
        ).all()

        for dispute in deadlocks:
            logger.info(f"Dispute {dispute.id} in deadlock (> 7 days). Forcing buyer protection refund.")
            payload = {
                "resolution": "refund_full",
                "notes": "SYSTEM MEDIATION CLOSURE: Mediasi melewati batas maksimal 7 hari tanpa resolusi pasti. Menerapkan protokol Perlindungan Pembeli (Buyer Protection)."
            }
            call_internal_api(f"/disputes/{dispute.id}/auto-resolve", payload)

    finally:
        db.close()


# =========================================================================
# CASE 5: Gagal Transfer (Payment Gateway Retry Mechanism)
# =========================================================================
def retry_failed_refunds():
    """Mengeksekusi ulang pencairan dana (refund payout) yang gagal (maksimal 3x)."""
    logger.info("Running task: Retry Failed Refunds...")
    db: Session = SessionLocal()
    try:
        # Ambil antrean transfer yang gagal dan batas coba ulangnya belum habis
        failed_payouts = db.query(RefundPayout).filter(
            RefundPayout.status == 'failed',
            RefundPayout.retry_count < 3
        ).all()

        for payout in failed_payouts:
            logger.info(f"Retrying refund payout {payout.id} (Attempt {payout.retry_count + 1}/3)")
            success = call_internal_api(f"/refund-payouts/{payout.id}/retry")
            
            # Jika ini adalah percobaan ke-3 dan masih gagal, kita berikan peringatan ekstra (Opsional: Slack/Discord Alert)
            if not success and payout.retry_count >= 2:
                logger.critical(f"CRITICAL: Refund Payout {payout.id} FAILED after 3 attempts! Manual intervention required.")

    finally:
        db.close()