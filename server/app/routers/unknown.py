import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_token
from app.database import get_db
from app.models import UnknownLog
from app.schemas import UnknownRequest, UnknownResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/unknown", response_model=UnknownResponse, status_code=201)
async def report_unknown(
    payload: UnknownRequest,
    device_id: str = Depends(verify_token),
    db: AsyncSession = Depends(get_db),
):
    log_entry = UnknownLog(
        timestamp=payload.timestamp,
        device_id=payload.device_id,
        location=payload.location,
        note=payload.note,
    )
    db.add(log_entry)
    await db.commit()
    await db.refresh(log_entry)
    logger.info("Unknown face logged from device=%s", payload.device_id)
    return log_entry
