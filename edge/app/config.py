import os

import cv2


SERVER_URL = os.getenv("SERVER_URL", "http://server:8000")
JWT_SECRET = os.getenv("JWT_SECRET", "aiot-face-attendance-jwt-secret-2025")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

DEVICE_ID = os.getenv("DEVICE_ID", "pi_emulator_01")
DEVICE_LOCATION = os.getenv("DEVICE_LOCATION", "Classroom B201")
_cam_raw = os.getenv("CAMERA_SOURCE", "/app/test_videos/classroom_demo.mp4")
CAMERA_SOURCE: int | str = int(_cam_raw) if _cam_raw.isdigit() else _cam_raw
CAMERA_BACKEND: int | None = (
    cv2.CAP_DSHOW
    if os.getenv("CAMERA_BACKEND", "").upper() == "DSHOW"
    else None
)

DISTANCE_THRESHOLD = float(os.getenv("DISTANCE_THRESHOLD", "0.5"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "5"))

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
PROCESS_EVERY_N = 4
RESIZE_SCALE = 0.5
DETECTION_MODEL = "hog"

OFFLINE_QUEUE_DB = os.getenv("OFFLINE_QUEUE_DB", "/app/data/offline_queue.db")
OFFLINE_RETRY_INTERVAL = 30
OFFLINE_MAX_RETRIES = 3

EDGE_API_PORT = int(os.getenv("EDGE_API_PORT", "8001"))

ENROLL_SAMPLES = int(os.getenv("ENROLL_SAMPLES", "15"))
ENROLL_TIMEOUT = int(os.getenv("ENROLL_TIMEOUT", "60"))
ENROLL_MIN_FACE_SIZE = 80
ENROLL_DUPLICATE_THRESHOLD = 0.05
