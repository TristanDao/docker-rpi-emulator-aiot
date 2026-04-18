import base64
import logging
import os
from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_token
from app.config import settings
from app.database import get_db
from app.models import Attendance
from app.schemas import AttendanceRequest, AttendanceResponse, AttendanceResult

router = APIRouter()
logger = logging.getLogger(__name__)

_last_seen: dict[int, float] = {}

SNAPSHOT_DIR = "/app/attendance_snapshots"


def _save_snapshot(b64_data: str, user_id: int, date, shift: int, action: str) -> str:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    filename = f"{user_id}_{date}_{shift}_{action.lower()}.jpg"
    filepath = os.path.join(SNAPSHOT_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(base64.b64decode(b64_data))
    return filename


@router.post("/attendance", response_model=AttendanceResult)
async def record_attendance(
    payload: AttendanceRequest,
    device_id: str = Depends(verify_token),
    db: AsyncSession = Depends(get_db),
):
    user_id = payload.user_id
    now_ts = payload.timestamp.timestamp()

    last = _last_seen.get(user_id)
    if last is not None and (now_ts - last) < settings.cooldown_seconds:
        return AttendanceResult(action="IGNORED", message="Cooldown active")
    _last_seen[user_id] = now_ts

    today = payload.timestamp.date()

    result = await db.execute(
        select(Attendance)
        .where(and_(Attendance.user_id == user_id, Attendance.date == today))
        .order_by(Attendance.shift.desc())
    )
    latest_record = result.scalars().first()

    if latest_record is None:
        record = Attendance(
            user_id=user_id,
            date=today,
            check_in=payload.timestamp,
            shift=1,
            status="present",
            device_id=payload.device_id,
            match_distance=payload.match_distance,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        if payload.snapshot_b64:
            try:
                filename = _save_snapshot(payload.snapshot_b64, user_id, today, 1, "check_in")
                record.check_in_image = filename
                await db.commit()
                await db.refresh(record)
            except Exception as exc:
                logger.warning("Failed to save check-in snapshot: %s", exc)
        logger.info("CHECK-IN user_id=%d shift=1", user_id)
        return AttendanceResult(
            action="CHECK_IN",
            message="Check-in recorded (shift 1)",
            record=AttendanceResponse.model_validate(record),
        )

    if latest_record.check_out is None:
        delta = (payload.timestamp - latest_record.check_in).total_seconds()
        latest_record.check_out = payload.timestamp
        latest_record.duration = int(delta)
        if payload.snapshot_b64:
            try:
                filename = _save_snapshot(
                    payload.snapshot_b64, user_id, today, latest_record.shift, "check_out"
                )
                latest_record.check_out_image = filename
            except Exception as exc:
                logger.warning("Failed to save check-out snapshot: %s", exc)
        await db.commit()
        await db.refresh(latest_record)
        logger.info("CHECK-OUT user_id=%d duration=%ds", user_id, int(delta))
        return AttendanceResult(
            action="CHECK_OUT",
            message=f"Check-out recorded, duration={int(delta)}s",
            record=AttendanceResponse.model_validate(latest_record),
        )

    new_shift = latest_record.shift + 1
    record = Attendance(
        user_id=user_id,
        date=today,
        check_in=payload.timestamp,
        shift=new_shift,
        status="present",
        device_id=payload.device_id,
        match_distance=payload.match_distance,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    if payload.snapshot_b64:
        try:
            filename = _save_snapshot(
                payload.snapshot_b64, user_id, today, new_shift, "check_in"
            )
            record.check_in_image = filename
            await db.commit()
            await db.refresh(record)
        except Exception as exc:
            logger.warning("Failed to save check-in snapshot: %s", exc)
    logger.info("CHECK-IN user_id=%d shift=%d", user_id, new_shift)
    return AttendanceResult(
        action="CHECK_IN",
        message=f"Check-in recorded (shift {new_shift})",
        record=AttendanceResponse.model_validate(record),
    )


@router.get("/attendance", response_model=list[AttendanceResponse])
async def list_attendance(
    date_str: Optional[str] = Query(None, alias="date"),
    user_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Attendance)
    if date_str:
        try:
            d = date_type.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
        query = query.where(Attendance.date == d)
    if user_id:
        query = query.where(Attendance.user_id == user_id)
    result = await db.execute(query.order_by(Attendance.id))
    return result.scalars().all()
