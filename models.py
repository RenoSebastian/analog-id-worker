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

    # Pastikan createdAt / updatedAt eksisting tetap aman
    createdAt = Column(DateTime, default=datetime.datetime.utcnow)
    updatedAt = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class GradingRequest(Base):
    """
    SHADOW MODEL: Hanya untuk READ operations permintaan video grading.
    """
    __tablename__ = "grading_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)