from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

# Import spesifik dari folder tasks dan file order_tasks
from tasks.order_tasks import cancel_unpaid_orders_task, auto_complete_shipped_orders_task

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

    logger.debug("Scheduler rules berhasil dikonfigurasi.")
    return scheduler