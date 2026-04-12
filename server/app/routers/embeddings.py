import base64
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_token
from app.database import get_db
from app.models import FaceEmbedding
from app.schemas import EmbeddingItem, EmbeddingSyncResponse

router = APIRouter()


@router.get("/embeddings/sync", response_model=EmbeddingSyncResponse)
async def sync_embeddings(
    last_sync_time: Optional[str] = None,
    device_id: str = Depends(verify_token),
    db: AsyncSession = Depends(get_db),
):
    query = select(FaceEmbedding)

    if last_sync_time:
        try:
            cutoff = datetime.fromisoformat(last_sync_time)
            query = query.where(FaceEmbedding.updated_at > cutoff)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid datetime format for last_sync_time")

    result = await db.execute(query.order_by(FaceEmbedding.id))
    rows = result.scalars().all()

    items = [
        EmbeddingItem(
            user_id=row.user_id,
            embedding_b64=base64.b64encode(row.embedding).decode(),
            model_type=row.model_type,
        )
        for row in rows
    ]
    return EmbeddingSyncResponse(count=len(items), embeddings=items)
