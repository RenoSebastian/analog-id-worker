from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

# Import spesifik dari folder tasks
from tasks.order_tasks import cancel_unpaid_orders_task, auto_complete_shipped_orders_task

# IMPORT BARU: Task Grading
from tasks.grading_tasks import expire_stale_grading_task # pyright: ignore[reportMissingImports]

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

    # --- JOB 3 BARU: Auto-Expire Grading setiap 30 menit ---
    scheduler.add_job(
        expire_stale_grading_task,
        trigger='interval',
        minutes=30,
        id='job_expire_grading_tickets',
        name='Expire Stale Grading Tickets Checker',
        replace_existing=True
    )

    logger.debug("Scheduler rules berhasil dikonfigurasi.")
    return scheduler