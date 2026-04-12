import logging
import time
from typing import Optional

import face_recognition
import numpy as np

from app.config import DISTANCE_THRESHOLD, COOLDOWN_SECONDS

logger = logging.getLogger(__name__)


class FaceRecognizer:
    """Compare unknown face encodings against known embeddings using vectorized Euclidean distance."""

    def __init__(self):
        self._known_encodings: list[np.ndarray] = []
        self._known_labels: list[dict] = []
        self._last_seen: dict[int, float] = {}

    def load_embeddings(self, encodings: list[np.ndarray], labels: list[dict]):
        self._known_encodings = encodings
        self._known_labels = labels
        logger.info("Loaded %d embeddings for %d unique users",
                     len(encodings), len(set(l["user_id"] for l in labels)))

    def recognize(self, encoding: np.ndarray) -> Optional[dict]:
        """
        Match an unknown encoding against all known.
        Returns {"user_id": int, "distance": float, "confidence": float}
        or None if no match.
        """
        if not self._known_encodings:
            return None

        distances = face_recognition.face_distance(self._known_encodings, encoding)
        min_idx = int(np.argmin(distances))
        min_distance = distances[min_idx]

        if min_distance >= DISTANCE_THRESHOLD:
            return None

        label = self._known_labels[min_idx]
        return {
            "user_id": label["user_id"],
            "distance": float(min_distance),
            "confidence": round(1.0 - float(min_distance), 4),
        }

    def is_cooldown_active(self, user_id: int) -> bool:
        now = time.time()
        last = self._last_seen.get(user_id)
        if last is not None and (now - last) < COOLDOWN_SECONDS:
            return True
        self._last_seen[user_id] = now
        return False
