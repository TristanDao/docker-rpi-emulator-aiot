from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer,
    LargeBinary, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(50), unique=True, nullable=False, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(100))
    class_name = Column(String(50))
    role = Column(String(20), default="student")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    embeddings = relationship("FaceEmbedding", back_populates="user", cascade="all, delete-orphan")
    attendances = relationship("Attendance", back_populates="user")


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    embedding = Column(LargeBinary, nullable=False)
    model_type = Column(String(20), default="face_recognition")
    image_ref = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    user = relationship("User", back_populates="embeddings")

    __table_args__ = (
        Index("idx_embeddings_user", "user_id"),
        Index("idx_embeddings_updated", "updated_at"),
    )


class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    check_in = Column(DateTime(timezone=True))
    check_out = Column(DateTime(timezone=True))
    duration = Column(Integer)
    shift = Column(Integer, default=1)
    status = Column(String(20), default="present")
    device_id = Column(String(50))
    match_distance = Column(Float)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    user = relationship("User", back_populates="attendances")

    __table_args__ = (
        UniqueConstraint("user_id", "date", "shift", name="uq_user_date_shift"),
        Index("idx_attendance_user_date", "user_id", "date"),
        Index("idx_attendance_date", "date"),
    )


class UnknownLog(Base):
    __tablename__ = "unknown_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    image_path = Column(String(255))
    device_id = Column(String(50), nullable=False)
    location = Column(String(100))
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("idx_unknown_timestamp", "timestamp"),
        Index("idx_unknown_device", "device_id"),
    )
