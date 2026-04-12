import base64
import logging

import cv2
import face_recognition
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import FaceEmbedding, User
from app.schemas import EdgeEnrollRequest, EnrollmentResult, EnrollmentStatus

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/enroll/upload", response_model=EnrollmentResult)
async def enroll_from_upload(
    user_id: int,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    success_count = 0
    errors = []

    for idx, file in enumerate(files):
        try:
            contents = await file.read()
            nparr = np.frombuffer(contents, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is None:
                errors.append({"index": idx, "reason": "INVALID_IMAGE"})
                continue

            rgb_image = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_image, model="hog")

            if len(face_locations) != 1:
                errors.append({
                    "index": idx,
                    "reason": "INVALID_FACE_COUNT",
                    "count": len(face_locations),
                })
                continue

            encodings = face_recognition.face_encodings(rgb_image, face_locations)
            if not encodings:
                errors.append({"index": idx, "reason": "ENCODING_FAILED"})
                continue

            embedding_bytes = encodings[0].tobytes()
            record = FaceEmbedding(
                user_id=user_id,
                embedding=embedding_bytes,
                model_type="face_recognition",
            )
            db.add(record)
            await db.commit()
            success_count += 1

        except Exception as e:
            errors.append({"index": idx, "reason": "EXCEPTION", "detail": str(e)})
            logger.exception("Error processing image %d for user %d", idx, user_id)

    total = len(files)
    return EnrollmentResult(
        user_id=user_id,
        success_count=success_count,
        total=total,
        success_rate=success_count / total if total > 0 else 0,
        errors=errors,
        status="success" if success_count > 0 else "failed",
    )


@router.post("/enroll/embedding", response_model=EnrollmentResult)
async def enroll_from_edge(
    payload: EdgeEnrollRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == payload.user_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="User not found")

    if not payload.embeddings_b64:
        raise HTTPException(status_code=400, detail="No embeddings provided")

    success_count = 0
    errors = []
    expected_size = 128 * 8  # 128 float64 values = 1024 bytes

    for idx, emb_b64 in enumerate(payload.embeddings_b64):
        try:
            raw = base64.b64decode(emb_b64)
            if len(raw) != expected_size:
                errors.append({"index": idx, "reason": "INVALID_EMBEDDING_SIZE"})
                continue

            record = FaceEmbedding(
                user_id=payload.user_id,
                embedding=raw,
                model_type="face_recognition",
                image_ref=f"edge:{payload.device_id}",
            )
            db.add(record)
            await db.commit()
            success_count += 1

        except Exception as e:
            errors.append({"index": idx, "reason": "EXCEPTION", "detail": str(e)})
            logger.exception(
                "Error saving embedding %d for user %d", idx, payload.user_id,
            )

    total = len(payload.embeddings_b64)
    return EnrollmentResult(
        user_id=payload.user_id,
        success_count=success_count,
        total=total,
        success_rate=success_count / total if total > 0 else 0,
        errors=errors,
        status="success" if success_count > 0 else "failed",
    )


@router.delete("/users/{user_id}/embeddings")
async def reset_enrollment(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        delete(FaceEmbedding).where(FaceEmbedding.user_id == user_id)
    )
    await db.commit()
    return {"deleted_count": result.rowcount, "status": "ok"}


@router.get("/users/{user_id}/enrollment-status", response_model=EnrollmentStatus)
async def get_enrollment_status(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(func.count()).where(FaceEmbedding.user_id == user_id)
    )
    count = result.scalar() or 0
    return EnrollmentStatus(
        user_id=user_id,
        enrolled=count > 0,
        sample_count=count,
        is_sufficient=count >= 10,
    )
