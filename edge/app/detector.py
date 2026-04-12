import logging

import cv2
import face_recognition
import numpy as np

from app.config import RESIZE_SCALE, DETECTION_MODEL

logger = logging.getLogger(__name__)


def detect_and_encode(frame: np.ndarray) -> list[tuple[tuple, np.ndarray]]:
    """
    Detect faces in a frame and extract 128D embeddings.
    Returns list of (face_location_original_scale, encoding) tuples.
    """
    small_frame = cv2.resize(frame, (0, 0), fx=RESIZE_SCALE, fy=RESIZE_SCALE)
    rgb_small = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

    face_locations = face_recognition.face_locations(rgb_small, model=DETECTION_MODEL)

    if not face_locations:
        return []

    encodings = face_recognition.face_encodings(rgb_small, face_locations)

    inv_scale = 1.0 / RESIZE_SCALE
    results = []
    for loc, enc in zip(face_locations, encodings):
        top, right, bottom, left = loc
        original_loc = (
            int(top * inv_scale),
            int(right * inv_scale),
            int(bottom * inv_scale),
            int(left * inv_scale),
        )
        results.append((original_loc, enc))

    return results
