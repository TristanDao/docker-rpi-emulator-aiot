from datetime import datetime, date
from typing import Optional

from pydantic import BaseModel


# ── Users ──

class UserCreate(BaseModel):
    student_id: str
    full_name: str
    email: Optional[str] = None
    class_name: Optional[str] = None
    role: str = "student"


class UserResponse(BaseModel):
    id: int
    student_id: str
    full_name: str
    email: Optional[str]
    class_name: Optional[str]
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Attendance ──

class AttendanceRequest(BaseModel):
    user_id: int
    timestamp: datetime
    confidence: float
    match_distance: float
    device_id: str
    location: Optional[str] = None


class AttendanceResponse(BaseModel):
    id: int
    user_id: int
    date: date
    check_in: Optional[datetime]
    check_out: Optional[datetime]
    duration: Optional[int]
    shift: int
    status: str
    device_id: Optional[str]
    match_distance: Optional[float]

    class Config:
        from_attributes = True


class AttendanceResult(BaseModel):
    action: str
    message: str
    record: Optional[AttendanceResponse] = None


# ── Unknown ──

class UnknownRequest(BaseModel):
    timestamp: datetime
    device_id: str
    location: Optional[str] = None
    note: Optional[str] = None


class UnknownResponse(BaseModel):
    id: int
    timestamp: datetime
    device_id: str
    location: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Embeddings Sync ──

class EmbeddingItem(BaseModel):
    user_id: int
    embedding_b64: str
    model_type: str


class EmbeddingSyncResponse(BaseModel):
    count: int
    embeddings: list[EmbeddingItem]


# ── Enrollment ──

class EdgeEnrollRequest(BaseModel):
    user_id: int
    embeddings_b64: list[str]
    device_id: str


class EnrollmentResult(BaseModel):
    user_id: int
    success_count: int
    total: int
    success_rate: float
    errors: list[dict]
    status: str


class EnrollmentStatus(BaseModel):
    user_id: int
    enrolled: bool
    sample_count: int
    is_sufficient: bool
