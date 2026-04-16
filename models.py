import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from database import Base

class Order(Base):
    """
    SHADOW MODEL: Hanya untuk READ operations status pesanan.
    Di-manage secara penuh oleh Sequelize di Node.js.
    """
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(String, nullable=False)
    
    # Sinkronisasi Atribut Fisik Logistik
    product_weight = Column(Integer, nullable=False, default=0)
    product_length = Column(Integer, nullable=False, default=0)
    product_width = Column(Integer, nullable=False, default=0)
    product_height = Column(Integer, nullable=False, default=0)

    # (FIXED): Perbaikan pemanggilan fungsi utcnow agar tidak error 
    # karena import di atas adalah 'from datetime import datetime'
    createdAt = Column(DateTime, default=datetime.utcnow)
    updatedAt = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GradingRequest(Base):
    """
    SHADOW MODEL: Untuk pencarian (READ) dan penguncian baris (with_for_update) 
    oleh Cronjob untuk mengecek masa kedaluwarsa 3x24 Jam tiket verifikasi premium.
    Di-manage secara penuh oleh Sequelize di Node.js.
    """
    __tablename__ = "grading_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # --- PENAMBAHAN KOLOM RELASI ---
    # Membantu Python Worker jika membutuhkan referensi user/produk 
    # saat mengirim payload webhook/API internal ke Node.js
    buyer_id = Column(UUID(as_uuid=True), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    
    # Menggunakan String adalah teknik paling aman untuk membaca ENUM dari bahasa/framework lain
    status = Column(String, nullable=False)
    
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)