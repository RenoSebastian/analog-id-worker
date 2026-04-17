from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

# Import spesifik dari folder tasks
from tasks.order_tasks import cancel_unpaid_orders_task, auto_complete_shipped_orders_task

# IMPORT BARU: Task Grading & Auction
from tasks.grading_tasks import expire_stale_grading_task # pyright: ignore[reportMissingImports]
from tasks.auction_tasks import (
    task_freeze_nearing_auctions, 
    task_evaluate_winners, 
    task_runner_up_handover
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

    # Job 4: Freeze Lelang (Masa Tenang T-15s) - Interval 5 Detik untuk presisi tinggi
    scheduler.add_job(
        task_freeze_nearing_auctions,
        trigger='interval',
        seconds=5,
        id='job_freeze_auctions',
        name='Auction Freeze State Synchronizer',
        replace_existing=True
    )

    # Job 5: Evaluasi Pemenang Lelang - Interval 1 Menit
    scheduler.add_job(
        task_evaluate_winners,
        trigger='interval',
        minutes=1,
        id='job_evaluate_auction_winners',
        name='Auction Winner Evaluation & Auto-Order',
        replace_existing=True
    )

    # Job 6: SLA Handover ke Runner Up (Gagal bayar 24 Jam) - Interval 5 Menit
    scheduler.add_job(
        task_runner_up_handover,
        trigger='interval',
        minutes=5,
        id='job_runner_up_handover',
        name='Auction Runner Up Handover (SLA Monitor)',
        replace_existing=True
    )

    logger.debug("Scheduler rules berhasil dikonfigurasi.")
    return scheduler