import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routers import attendance, dashboard, embeddings, enrollment, unknown, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    os.makedirs("/app/attendance_snapshots", exist_ok=True)
    yield


app = FastAPI(
    title="Face Attendance API",
    description="AIoT Face Recognition Attendance System — Backend Server",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(attendance.router, prefix="/api", tags=["Attendance"])
app.include_router(users.router, prefix="/api", tags=["Users"])
app.include_router(enrollment.router, prefix="/api", tags=["Enrollment"])
app.include_router(embeddings.router, prefix="/api", tags=["Embeddings"])
app.include_router(unknown.router, prefix="/api", tags=["Unknown"])
app.include_router(dashboard.router, tags=["Dashboard"])


@app.get("/health")
async def health_check():
    return {"status": "ok"}
