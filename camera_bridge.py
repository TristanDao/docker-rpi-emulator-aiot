"""
camera_bridge.py — Capture USB webcam on any OS and serve as MJPEG HTTP stream.

The Docker edge container reads this stream via:
  Windows : CAMERA_SOURCE=http://<LAN-IP>:8888/stream.mjpg
  Mac     : CAMERA_SOURCE=http://host.docker.internal:8888/stream.mjpg

Usage:
  conda activate edge
  python camera_bridge.py [--index -1] [--port 8888] [--width 640] [--height 480]
  # --index -1  auto-detects the first working camera
"""

import argparse
import logging
import platform
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [camera_bridge] %(levelname)s: %(message)s",
)
logger = logging.getLogger("camera_bridge")

# ── globals ────────────────────────────────────────────────────────────────────
_frame_lock = threading.Lock()
_latest_jpeg: bytes = b""
_frame_count = 0
_start_time = time.time()


def _best_backend() -> int:
    """Return the best OpenCV camera backend for the current OS."""
    system = platform.system()
    if system == "Windows":
        return cv2.CAP_DSHOW
    if system == "Darwin":
        return cv2.CAP_AVFOUNDATION
    # Linux — default backend (V4L2)
    return cv2.CAP_V4L2


def _capture_loop(index: int, width: int, height: int, fps: int) -> None:
    global _latest_jpeg, _frame_count

    backend = _best_backend()
    backend_name = {cv2.CAP_DSHOW: "DSHOW", cv2.CAP_AVFOUNDATION: "AVFOUNDATION",
                    cv2.CAP_V4L2: "V4L2"}.get(backend, str(backend))

    logger.info("Opening camera index=%d (backend=%s)…", index, backend_name)
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        logger.warning("%s failed, retrying with default backend…", backend_name)
        cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        logger.error("Cannot open camera index=%d. Is the webcam connected?", index)
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    logger.info("Camera opened: %dx%d", actual_w, actual_h)

    encode_params = [cv2.IMWRITE_JPEG_QUALITY, 80]

    while True:
        ret, frame = cap.read()
        if not ret:
            logger.warning("Frame read failed, retrying…")
            time.sleep(0.1)
            continue

        ok, buf = cv2.imencode(".jpg", frame, encode_params)
        if ok:
            with _frame_lock:
                _latest_jpeg = buf.tobytes()
                _frame_count += 1

    cap.release()


class _MjpegHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # suppress per-request logs
        pass

    def do_GET(self):
        if self.path == "/stream.mjpg":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                while True:
                    with _frame_lock:
                        jpeg = _latest_jpeg
                    if jpeg:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    time.sleep(0.033)  # ~30 fps cap
            except (BrokenPipeError, ConnectionResetError):
                pass

        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            elapsed = time.time() - _start_time
            self.wfile.write(
                f'{{"status":"ok","frames":{_frame_count},'
                f'"uptime_s":{elapsed:.1f}}}'.encode()
            )

        else:
            self.send_response(404)
            self.end_headers()


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _auto_detect_camera() -> int:
    """Scan indexes 0-9 with the best backend and return first working one."""
    backend = _best_backend()
    try:
        for i in range(10):
            cap = cv2.VideoCapture(i, backend)
            if cap.isOpened():
                ret, _ = cap.read()
                cap.release()
                if ret:
                    logger.info("Auto-detected camera at index %d", i)
                    return i
            cap.release()
    except Exception:
        pass
    logger.warning("Auto-detect failed, defaulting to index 0")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="USB webcam → MJPEG HTTP bridge")
    parser.add_argument("--index", type=int, default=-1, help="Camera device index (-1 = auto-detect)")
    parser.add_argument("--port", type=int, default=8888, help="HTTP port (default: 8888)")
    parser.add_argument("--width", type=int, default=640, help="Frame width (default: 640)")
    parser.add_argument("--height", type=int, default=480, help="Frame height (default: 480)")
    parser.add_argument("--fps", type=int, default=30, help="Target FPS (default: 30)")
    args = parser.parse_args()

    if args.index == -1:
        args.index = _auto_detect_camera()

    capture_thread = threading.Thread(
        target=_capture_loop,
        args=(args.index, args.width, args.height, args.fps),
        daemon=True,
    )
    capture_thread.start()

    # Wait for first frame
    logger.info("Waiting for first frame…")
    deadline = time.time() + 15
    while not _latest_jpeg and time.time() < deadline:
        time.sleep(0.2)

    if not _latest_jpeg:
        system = platform.system()
        hint = {
            "Windows": "python -c \"import cv2; [print(i, cv2.VideoCapture(i,cv2.CAP_DSHOW).isOpened()) for i in range(4)]\"",
            "Darwin":  "python -c \"import cv2; [print(i, cv2.VideoCapture(i,cv2.CAP_AVFOUNDATION).isOpened()) for i in range(4)]\"",
        }.get(system, "python -c \"import cv2; [print(i, cv2.VideoCapture(i).isOpened()) for i in range(4)]\"")
        logger.error("No frame received within 15s. Check camera index with:\n  %s", hint)
        return

    logger.info("First frame received. Starting HTTP server on port %d…", args.port)

    local_ip = _get_local_ip()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), _MjpegHandler)

    system = platform.system()
    docker_hint = "host.docker.internal" if system in ("Darwin", "Linux") else local_ip

    logger.info("MJPEG stream ready:")
    logger.info("  Local browser : http://localhost:%d/stream.mjpg", args.port)
    logger.info("  Docker edge   : http://%s:%d/stream.mjpg  <-- use this in .env CAMERA_SOURCE", docker_hint, args.port)
    logger.info("  Health check  : http://localhost:%d/health", args.port)
    logger.info("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopped.")


if __name__ == "__main__":
    main()
