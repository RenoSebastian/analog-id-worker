from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

# Import spesifik dari folder tasks
from tasks.order_tasks import cancel_unpaid_orders_task, auto_complete_shipped_orders_task

# IMPORT BARU: Task Grading & Auction
from tasks.grading_tasks import expire_stale_grading_task # pyright: ignore[reportMissingImports]
from tasks.auction_tasks import (
    task_freeze_nearing_auctions, 
    task_evaluate_winners, 
    task_runner_up_handover,
    task_start_scheduled_auctions  # ⚡ FIX: Import fungsi inisialisasi lelang
)

# ⚡ BARU: Import Task Otomatisasi Dispute & Refund
from tasks.dispute_tasks import (
    check_admin_inactivity,
    check_seller_unresponsive,
    check_buyer_no_response,
    check_mediation_deadlock,
    retry_failed_refunds
)

def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    # Job 1: Auto-Cancel setiap 10 menit
    scheduler.add_job(
        cancel_unpaid_orders_task,
        trigger='interval',
        minutes=10,
        id='job_cancel_unpaid_orders',
        name='Cancel Unpaid Orders Checker',
        replace_existing=True
    )

    # Job 2: Auto-Complete setiap 1 jam
    scheduler.add_job(
        auto_complete_shipped_orders_task,
        trigger='interval',
        hours=1,
        id='job_auto_complete_shipped',
        name='Auto Complete Shipped Orders Checker',
        replace_existing=True
    )

    # Job 3: Auto-Expire Grading setiap 30 menit
    scheduler.add_job(
        expire_stale_grading_task,
        trigger='interval',
        minutes=30,
        id='job_expire_grading_tickets',
        name='Expire Stale Grading Tickets Checker',
        replace_existing=True
    )

    # ==========================================
    # WORKER MODUL LELANG (AUCTION)
    # ==========================================

    # ⚡ FIX: Job 4 - Memulai Lelang & Inisialisasi Redis (Interval 5 Detik)
    scheduler.add_job(
        task_start_scheduled_auctions,
        trigger='interval',
        seconds=5,
        id='job_start_scheduled_auctions',
        name='Start Scheduled Auctions Initializer',
        replace_existing=True
    )

    # Job 5: Freeze Lelang (Masa Tenang T-15s) - Interval 5 Detik untuk presisi tinggi
    scheduler.add_job(
        task_freeze_nearing_auctions,
        trigger='interval',
        seconds=5,
        id='job_freeze_auctions',
        name='Auction Freeze State Synchronizer',
        replace_existing=True
    )

    # Job 6: Evaluasi Pemenang Lelang - Interval 1 Menit
    scheduler.add_job(
        task_evaluate_winners,
        trigger='interval',
        minutes=1,
        id='job_evaluate_auction_winners',
        name='Auction Winner Evaluation & Auto-Order',
        replace_existing=True
    )

    # Job 7: SLA Handover ke Runner Up (Gagal bayar 24 Jam) - Interval 5 Menit
    scheduler.add_job(
        task_runner_up_handover,
        trigger='interval',
        minutes=5,
        id='job_runner_up_handover',
        name='Auction Runner Up Handover (SLA Monitor)',
        replace_existing=True
    )

    # ==========================================
    # ⚡ BARU: WORKER MODUL DISPUTE & REFUND
    # ==========================================

    # Job 8: SLA Inaktivitas Admin/Penjual setelah barang retur sampai (Setiap 1 Jam)
    scheduler.add_job(
        check_admin_inactivity,
        trigger='interval',
        hours=1,
        id='job_dispute_admin_inactivity',
        name='Dispute SLA: Admin/Seller Inactivity Checker',
        replace_existing=True
    )

    # Job 9: SLA Penjual tidak merespon komplain awal (Setiap 1 Jam)
    scheduler.add_job(
        check_seller_unresponsive,
        trigger='interval',
        hours=1,
        id='job_dispute_seller_unresponsive',
        name='Dispute SLA: Seller Unresponsive Checker',
        replace_existing=True
    )

    # Job 10: SLA Pembeli tidak memasukkan resi pengembalian (Setiap 1 Jam)
    scheduler.add_job(
        check_buyer_no_response,
        trigger='interval',
        hours=1,
        id='job_dispute_buyer_no_response',
        name='Dispute SLA: Buyer No-Response Checker',
        replace_existing=True
    )

    # Job 11: SLA Mediasi menggantung/Deadlock (Setiap 12 Jam)
    scheduler.add_job(
        check_mediation_deadlock,
        trigger='interval',
        hours=12,
        id='job_dispute_mediation_deadlock',
        name='Dispute SLA: Mediation Deadlock Monitor',
        replace_existing=True
    )

    # Job 12: Retry Pencairan Dana / Refund yang gagal di Payment Gateway (Setiap 10 Menit)
    scheduler.add_job(
        retry_failed_refunds,
        trigger='interval',
        minutes=10,
        id='job_refund_retry_mechanism',
        name='Refund Payout: Failed Transactions Retry Mechanism',
        replace_existing=True
    )

    logger.debug("Scheduler rules berhasil dikonfigurasi.")
    return scheduler