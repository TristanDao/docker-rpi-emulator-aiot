import logging

import cv2
import face_recognition
import numpy as np

from app.config import RESIZE_SCALE

logger = logging.getLogger(__name__)

_haar_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
if _haar_cascade.empty():
    logger.error("Failed to load Haar cascade XML — Haar detection will not work")


def detect_and_encode(
    frame: np.ndarray, detection_method: str = "hog"
) -> list[tuple[tuple, np.ndarray]]:
    """
    Detect faces in a frame and extract 128D embeddings.
    Returns list of (face_location_original_scale, encoding) tuples.

    detection_method: "hog" (default) or "haar"
    """
    small_frame = cv2.resize(frame, (0, 0), fx=RESIZE_SCALE, fy=RESIZE_SCALE)
    rgb_small = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

    if detection_method == "haar":
        gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
        rects = _haar_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
        )
        face_locations = [(y, x + w, y + h, x) for (x, y, w, h) in rects] if len(rects) else []
    else:
        face_locations = face_recognition.face_locations(rgb_small, model=detection_method)

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
