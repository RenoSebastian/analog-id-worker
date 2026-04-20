import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Numeric
from sqlalchemy.dialects.postgresql import UUID, ENUM
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

    created_at = Column("created_at", DateTime, default=datetime.now)
    updated_at = Column("updated_at", DateTime, default=datetime.now, onupdate=datetime.now)


class GradingRequest(Base):
    """
    SHADOW MODEL: Untuk pencarian (READ) dan penguncian baris.
    """
    __tablename__ = "grading_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    buyer_id = Column(UUID(as_uuid=True), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(String, nullable=False)
    
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now)


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


# DEFINISI ENUM POSTGRESQL (CRUCIAL FIX)
auction_status_enum = ENUM(
    'SCHEDULED', 'ACTIVE', 'FREEZE', 'EVALUATION', 'COMPLETED', 'FAILED', 'HANDOVER_TO_RUNNER_UP',
    name='enum_auctions_status',
    create_type=False # SANGAT KRUSIAL: Mencegah Python mengeksekusi CREATE TYPE di DB
)

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
    
    # Gunakan ENUM yang sudah didefinisikan di atas
    status = Column(auction_status_enum, nullable=False, default='DRAFT')


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
    created_at = Column(DateTime, default=datetime.now)

class User(Base):
    """
    SHADOW MODEL: Tabel Users.
    Diperlukan Worker untuk mengecek profil pemenang atau menambahkan penalti (Flagging).
    """
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)