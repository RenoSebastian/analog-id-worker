import asyncio
from database import get_db_session
from logger import logger
from sqlalchemy import text

async def test_connection():
    async with get_db_session() as session:
        result = await session.execute(text("SELECT 1"))
        logger.success(f"Connection Successful! Test result: {result.scalar()}")

if __name__ == "__main__":
    asyncio.run(test_connection())