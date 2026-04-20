import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Numeric
from sqlalchemy.dialects.postgresql import UUID, ENUM
from database import Base

# DEFINISI ENUM ORDER STATUS UNTUK MENCEGAH TYPE MISMATCH
order_status_enum = ENUM(
    'pending_payment', 'paid', 'processing', 'shipped', 'delivered', 
    'completed', 'cancelled', 'disputed',
    name='enum_orders_status',
    create_type=False # Mencegah pembuatan ulang tipe di database
)

class Order(Base):
    """
    SHADOW MODEL: Hanya untuk READ & WRITE operations status pesanan lelang/reguler.
    Di-manage secara penuh oleh Sequelize di Node.js.
    """
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(order_status_enum, nullable=False)
    
    auction_id = Column(UUID(as_uuid=True), nullable=True)
    buyer_id = Column(UUID(as_uuid=True), nullable=False)
    store_id = Column(UUID(as_uuid=True), nullable=False)
    subtotal = Column(Numeric(12, 2), nullable=False)
    shipping_fee = Column(Numeric(12, 2), nullable=False, default=0)
    grading_fee = Column(Numeric(12, 2), nullable=False, default=0)
    grand_total = Column(Numeric(12, 2), nullable=False)
    shipping_address = Column(String, nullable=False)
    
    created_at = Column("created_at", DateTime, default=datetime.now)
    updated_at = Column("updated_at", DateTime, default=datetime.now, onupdate=datetime.now)


class GradingRequest(Base):
    __tablename__ = "grading_requests"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    buyer_id = Column(UUID(as_uuid=True), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now)


class Product(Base):
    # Kolom is_locked dihapus karena lelang sudah terpisah dari produk reguler
    __tablename__ = "products"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), nullable=False)


# DEFINISI ENUM POSTGRESQL (CRUCIAL FIX)
auction_status_enum = ENUM(
    'SCHEDULED', 'ACTIVE', 'FREEZE', 'EVALUATION', 'COMPLETED', 'FAILED', 'HANDOVER_TO_RUNNER_UP',
    name='enum_auctions_status',
    create_type=False
)

class Auction(Base):
    """
    SHADOW MODEL: Induk Lelang yang kini berdiri sendiri secara independen.
    """
    __tablename__ = "auctions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # --- DECOUPLED DARI PRODUCT ---
    store_id = Column(UUID(as_uuid=True), nullable=False)
    item_name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    condition = Column(String, nullable=False, default='USED')
    weight = Column(Integer, nullable=False, default=0)
    length = Column(Integer, nullable=False, default=0)
    width = Column(Integer, nullable=False, default=0)
    height = Column(Integer, nullable=False, default=0)
    # ------------------------------

    winner_id = Column(UUID(as_uuid=True), nullable=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    increment = Column(Numeric(15, 2), nullable=False)
    current_price = Column(Numeric(15, 2), nullable=True)
    
    status = Column(auction_status_enum, nullable=False, default='DRAFT')


class AuctionBid(Base):
    __tablename__ = "auction_bids"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    auction_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    bid_amount = Column(Numeric(15, 2), nullable=False)
    status = Column(String, nullable=False, default='VALID')
    created_at = Column(DateTime, default=datetime.now)


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)