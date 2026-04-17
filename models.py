import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Numeric
from sqlalchemy.dialects.postgresql import UUID
from database import Base

class Order(Base):
    """
    SHADOW MODEL: Hanya untuk READ & WRITE operations status pesanan lelang/reguler.
    Di-manage secara penuh oleh Sequelize di Node.js.
    """
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(String, nullable=False)
    
    # --- PENAMBAHAN KOLOM UNTUK MODUL LELANG (AUTO-ORDER) ---
    auction_id = Column(UUID(as_uuid=True), nullable=True)
    buyer_id = Column(UUID(as_uuid=True), nullable=False)
    store_id = Column(UUID(as_uuid=True), nullable=False)
    subtotal = Column(Numeric(12, 2), nullable=False)
    shipping_fee = Column(Numeric(12, 2), nullable=False, default=0)
    grading_fee = Column(Numeric(12, 2), nullable=False, default=0)
    grand_total = Column(Numeric(12, 2), nullable=False)
    shipping_address = Column(String, nullable=False)
    
    # Sinkronisasi Atribut Fisik Logistik
    product_weight = Column(Integer, nullable=False, default=0)
    product_length = Column(Integer, nullable=False, default=0)
    product_width = Column(Integer, nullable=False, default=0)
    product_height = Column(Integer, nullable=False, default=0)

    # Note: Menggunakan argumen string 'created_at' agar SQLAlchemy mapping tepat ke nama kolom di DB 
    # (karena Node.js Sequelize menggunakan underscored: true)
    created_at = Column("created_at", DateTime, default=datetime.utcnow)
    updated_at = Column("updated_at", DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GradingRequest(Base):
    """
    SHADOW MODEL: Untuk pencarian (READ) dan penguncian baris.
    """
    __tablename__ = "grading_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    buyer_id = Column(UUID(as_uuid=True), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(String, nullable=False)
    
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


# ==========================================
# SHADOW MODELS UNTUK MODUL LELANG (BARU)
# ==========================================

class Product(Base):
    """
    SHADOW MODEL: Diperlukan untuk mengecek dan mengubah status is_locked
    saat lelang dimulai, selesai, atau gagal.
    """
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), nullable=False)
    is_locked = Column(Boolean, nullable=False, default=False)


class Auction(Base):
    """
    SHADOW MODEL: Induk Lelang. Digunakan Cronjob untuk evaluasi state/status.
    """
    __tablename__ = "auctions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    winner_id = Column(UUID(as_uuid=True), nullable=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    increment = Column(Numeric(15, 2), nullable=False)
    current_price = Column(Numeric(15, 2), nullable=False, default=0)
    status = Column(String, nullable=False, default='DRAFT')


class AuctionBid(Base):
    """
    SHADOW MODEL: Histori Audit Log Lelang. 
    Digunakan untuk menentukan Runner Up jika Pemenang Pertama gagal bayar.
    """
    __tablename__ = "auction_bids"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    auction_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    bid_amount = Column(Numeric(15, 2), nullable=False)
    status = Column(String, nullable=False, default='VALID')
    # Tabel append-only ini hanya memiliki created_at
    created_at = Column(DateTime, default=datetime.utcnow)