import base64
import logging
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
from jose import jwt

from app.config import SERVER_URL, JWT_SECRET, JWT_ALGORITHM, DEVICE_ID

logger = logging.getLogger(__name__)

_TOKEN_LIFETIME = timedelta(hours=23)
_token_cache: dict[str, object] = {}


def _get_token() -> str:
    cached_at = _token_cache.get("created_at")
    if cached_at and (datetime.now(timezone.utc) - cached_at) < _TOKEN_LIFETIME:
        return _token_cache["token"]

    now = datetime.now(timezone.utc)
    payload = {
        "sub": DEVICE_ID,
        "iss": "face-attendance-edge",
        "iat": now,
        "exp": now + timedelta(hours=24),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    _token_cache["token"] = token
    _token_cache["created_at"] = now
    logger.debug("JWT token refreshed, expires in 24h")
    return token


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}"}


async def send_attendance(user_id: int, timestamp: str, confidence: float,
                          match_distance: float, device_id: str,
                          location: str) -> dict | None:
    payload = {
        "user_id": user_id,
        "timestamp": timestamp,
        "confidence": confidence,
        "match_distance": match_distance,
        "device_id": device_id,
        "location": location,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SERVER_URL}/api/attendance",
                json=payload,
                headers=_headers(),
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error("Failed to send attendance: %s", e)
        return None


async def send_unknown(timestamp: str, device_id: str,
                       location: str) -> dict | None:
    payload = {
        "timestamp": timestamp,
        "device_id": device_id,
        "location": location,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SERVER_URL}/api/unknown",
                json=payload,
                headers=_headers(),
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error("Failed to send unknown event: %s", e)
        return None


async def fetch_user(user_id: int) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{SERVER_URL}/api/users/{user_id}")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error("Failed to fetch user %d: %s", user_id, e)
        return None


async def list_users() -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{SERVER_URL}/api/users")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error("Failed to list users: %s", e)
        return []


async def create_user(
    student_id: str,
    full_name: str,
    email: str | None = None,
    class_name: str | None = None,
    role: str = "student",
) -> dict | None:
    payload: dict = {"student_id": student_id, "full_name": full_name, "role": role}
    if email:
        payload["email"] = email
    if class_name:
        payload["class_name"] = class_name
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{SERVER_URL}/api/users", json=payload)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.json().get("detail", str(e)) if e.response else str(e)
        logger.error("Failed to create user: %s", detail)
        return {"__error__": detail}
    except Exception as e:
        logger.error("Failed to create user: %s", e)
        return None


async def send_enrollment(
    user_id: int, embeddings: list[np.ndarray], device_id: str,
) -> dict | None:
    payload = {
        "user_id": user_id,
        "embeddings_b64": [
            base64.b64encode(enc.tobytes()).decode() for enc in embeddings
        ],
        "device_id": device_id,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{SERVER_URL}/api/enroll/embedding",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error("Failed to send enrollment: %s", e)
        return None


async def fetch_embeddings(last_sync_time: str | None = None) -> list[dict]:
    params = {}
    if last_sync_time:
        params["last_sync_time"] = last_sync_time
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{SERVER_URL}/api/embeddings/sync",
                params=params,
                headers=_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("embeddings", []):
                enc = np.frombuffer(
                    base64.b64decode(item["embedding_b64"]),
                    dtype=np.float64,
                )
                results.append({
                    "user_id": item["user_id"],
                    "encoding": enc,
                    "model_type": item["model_type"],
                })
            logger.info("Fetched %d embeddings from server", len(results))
            return results
    except Exception as e:
        logger.error("Failed to fetch embeddings: %s", e)
        return []
