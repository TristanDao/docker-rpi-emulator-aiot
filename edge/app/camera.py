import logging
import threading
import queue
import time

import cv2

from app.config import CAMERA_SOURCE, CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_BACKEND

logger = logging.getLogger(__name__)


class CameraStream:
    """Threaded camera/video capture to avoid blocking the recognition loop."""

    def __init__(self, source=None, max_queue_size=2):
        self._source = source or CAMERA_SOURCE
        self._frame_queue = queue.Queue(maxsize=max_queue_size)
        self._stopped = False
        self._cap = None

    def start(self):
        if CAMERA_BACKEND is not None and isinstance(self._source, int):
            self._cap = cv2.VideoCapture(self._source, CAMERA_BACKEND)
        else:
            self._cap = cv2.VideoCapture(self._source)
        if not self._cap.isOpened():
            logger.error("Cannot open video source: %s", self._source)
            raise RuntimeError(f"Cannot open video source: {self._source}")

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

        thread = threading.Thread(target=self._capture_loop, daemon=True)
        thread.start()
        logger.info("Camera stream started: %s", self._source)
        return self

    def _capture_loop(self):
        consecutive_failures = 0
        max_failures = 5

        while not self._stopped:
            ret, frame = self._cap.read()
            if not ret:
                if self._is_video_file():
                    logger.info("Video ended, restarting from beginning")
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    consecutive_failures = 0
                    continue

                consecutive_failures += 1
                logger.warning(
                    "Camera read failed (%d/%d)%s",
                    consecutive_failures,
                    max_failures,
                    " — retrying..." if consecutive_failures < max_failures else "",
                )
                if consecutive_failures >= max_failures:
                    if self._is_http_stream():
                        logger.warning("HTTP stream lost. Attempting reconnect in 3s...")
                        time.sleep(3)
                        self._cap.release()
                        self._cap = cv2.VideoCapture(self._source)
                        consecutive_failures = 0
                        if not self._cap.isOpened():
                            logger.warning("Reconnect failed, will retry...")
                    else:
                        logger.warning("Camera read failed, stopping")
                        self._stopped = True
                        break
                else:
                    time.sleep(0.5)
                continue

            consecutive_failures = 0
            try:
                self._frame_queue.put_nowait(frame)
            except queue.Full:
                pass

            time.sleep(0.01)

    def read(self):
        try:
            return self._frame_queue.get(timeout=2.0)
        except queue.Empty:
            return None

    def stop(self):
        self._stopped = True
        if self._cap:
            self._cap.release()

    def is_running(self):
        return not self._stopped

    def _is_video_file(self):
        if isinstance(self._source, int):
            return False
        return not self._source.startswith(("/dev/", "rtsp://", "http://"))

    def _is_http_stream(self):
        return isinstance(self._source, str) and self._source.startswith("http://")
