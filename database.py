from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from config import settings
from logger import logger

# Memastikan URL menggunakan driver asyncpg (berjaga-jaga jika di .env tertulis postgres://)
db_url: str = settings.database_url
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Inisialisasi Async Engine dengan Connection Pooling yang efisien
engine = create_async_engine(
    db_url,
    echo=(settings.log_level.upper() == "DEBUG"), # Tampilkan raw SQL jika DEBUG
    future=True,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True # Cek kesehatan koneksi sebelum query dijalankan
)

# Factory untuk membuat sesi database
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False, # Penting untuk async agar objek tidak kadaluwarsa setelah commit
    autocommit=False,
    autoflush=False
)

Base = declarative_base()

@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager (dependency) asinkron untuk lifecycle sesi database.
    Memastikan koneksi selalu dikembalikan ke pool (close) walau terjadi error.
    """
    session: AsyncSession = AsyncSessionLocal()
    try:
        yield session
    except Exception as e:
        logger.error(f"Database session error: {e}")
        await session.rollback()
        raise
    finally:
        await session.close()