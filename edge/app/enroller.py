import logging
import time

import face_recognition
import numpy as np

from app.camera import CameraStream
from app.config import (
    ENROLL_DUPLICATE_THRESHOLD,
    ENROLL_MIN_FACE_SIZE,
    ENROLL_SAMPLES,
    ENROLL_TIMEOUT,
)
from app.detector import detect_and_encode

logger = logging.getLogger(__name__)


class EnrollmentSession:
    """Capture face samples from camera for enrollment."""

    def __init__(self, target_samples: int = ENROLL_SAMPLES, timeout: int = ENROLL_TIMEOUT):
        self._target = target_samples
        self._timeout = timeout
        self._samples: list[np.ndarray] = []

    @property
    def samples(self) -> list[np.ndarray]:
        return list(self._samples)

    @property
    def count(self) -> int:
        return len(self._samples)

    def capture(self) -> bool:
        """
        Open camera and collect face embeddings.
        Returns True if enough samples were collected.
        """
        camera = CameraStream()
        try:
            camera.start()
        except RuntimeError:
            logger.error("Cannot open camera for enrollment")
            return False

        start = time.monotonic()
        skipped_no_face = 0
        skipped_multi = 0
        skipped_small = 0
        skipped_dup = 0

        try:
            while self.count < self._target:
                elapsed = time.monotonic() - start
                if elapsed > self._timeout:
                    logger.warning(
                        "Enrollment timeout after %.0fs with %d/%d samples",
                        elapsed, self.count, self._target,
                    )
                    break

                frame = camera.read()
                if frame is None:
                    continue

                faces = detect_and_encode(frame)

                if len(faces) == 0:
                    skipped_no_face += 1
                    continue
                if len(faces) > 1:
                    skipped_multi += 1
                    continue

                face_loc, encoding = faces[0]

                top, right, bottom, left = face_loc
                face_h = bottom - top
                face_w = right - left
                if face_h < ENROLL_MIN_FACE_SIZE or face_w < ENROLL_MIN_FACE_SIZE:
                    skipped_small += 1
                    continue

                if self._is_duplicate(encoding):
                    skipped_dup += 1
                    continue

                self._samples.append(encoding)
                if self._samples:
                    prev_dist = face_recognition.face_distance(
                        [self._samples[-2]], encoding,
                    )[0] if len(self._samples) >= 2 else 0.0
                else:
                    prev_dist = 0.0

                logger.info(
                    "[%d/%d] Captured sample (dist from prev: %.3f)",
                    self.count, self._target, prev_dist,
                )

                time.sleep(0.3)

        finally:
            camera.stop()

        logger.info(
            "Enrollment capture done: %d/%d collected "
            "(skipped: no_face=%d multi=%d small=%d duplicate=%d)",
            self.count, self._target,
            skipped_no_face, skipped_multi, skipped_small, skipped_dup,
        )
        return self.count >= self._target

    def _is_duplicate(self, encoding: np.ndarray) -> bool:
        if not self._samples:
            return False
        distances = face_recognition.face_distance(self._samples, encoding)
        return float(np.min(distances)) < ENROLL_DUPLICATE_THRESHOLD
