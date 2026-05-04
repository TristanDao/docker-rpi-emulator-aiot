from datetime import datetime, timezone
from typing import Optional
import os

import cv2
import numpy as np

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

_GREEN = (0, 255, 0)
_RED = (0, 0, 255)
_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)
_FONT_CV = cv2.FONT_HERSHEY_SIMPLEX

# Font paths to try (order: prefer system fonts that have Vietnamese glyphs)
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",          # Linux (Docker)
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "C:/Windows/Fonts/arial.ttf",                                # Windows
    "C:/Windows/Fonts/calibri.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
]

_pil_font_label: Optional["ImageFont.FreeTypeFont"] = None
_pil_font_small: Optional["ImageFont.FreeTypeFont"] = None


def _load_fonts() -> None:
    global _pil_font_label, _pil_font_small
    if _pil_font_label is not None:
        return
    if not _PIL_AVAILABLE:
        return
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                _pil_font_label = ImageFont.truetype(path, 16)
                _pil_font_small = ImageFont.truetype(path, 13)
                return
            except Exception:
                continue
    # Fallback: PIL built-in bitmap font (no Unicode, but won't crash)
    _pil_font_label = ImageFont.load_default()
    _pil_font_small = ImageFont.load_default()


def _put_unicode_text(
    img: np.ndarray,
    text: str,
    pos: tuple[int, int],
    font: "ImageFont.FreeTypeFont",
    text_color: tuple[int, int, int],
    bg_color: Optional[tuple[int, int, int]] = None,
    padding: int = 4,
) -> None:
    """Draw Unicode text onto a BGR numpy array in-place using PIL."""
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)

    x, y = pos
    if bg_color is not None:
        bbox = font.getbbox(text)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.rectangle([x - padding, y - padding, x + w + padding, y + h + padding], fill=bg_color)

    draw.text((x, y), text, font=font, fill=text_color)
    img[:] = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def annotate_frame(
    frame: np.ndarray,
    faces: list[tuple[tuple, Optional[dict]]],
    user_names: dict[int, str],
    overlay_info: Optional[dict] = None,
) -> np.ndarray:
    """
    Draw bounding boxes, labels, and overlay info on a copy of the frame.

    faces: list of (face_location, match_result)
        - face_location: (top, right, bottom, left)
        - match_result: {"user_id", "confidence", "distance"} or None for unknown
    user_names: {user_id: full_name}
    overlay_info: {"device_id", "mode", "location"} for top-left overlay
    """
    _load_fonts()
    out = frame.copy()

    for face_loc, match in faces:
        top, right, bottom, left = face_loc

        if match:
            color = _GREEN
            uid = match["user_id"]
            name = user_names.get(uid, f"ID:{uid}")
            conf = match["confidence"] * 100
            label = f"{name} {conf:.1f}%"
        else:
            color = _RED
            label = "UNKNOWN"

        cv2.rectangle(out, (left, top), (right, bottom), color, 2)

        if _PIL_AVAILABLE and _pil_font_label is not None:
            label_y = max(top - 26, 0)
            _put_unicode_text(out, label, (left + 3, label_y), _pil_font_label, _WHITE, bg_color=color)
        else:
            label_h = 22
            label_y = max(top - label_h, 0)
            (tw, th), _ = cv2.getTextSize(label, _FONT_CV, 0.55, 1)
            cv2.rectangle(out, (left, label_y), (left + tw + 6, label_y + label_h), color, -1)
            cv2.putText(out, label, (left + 3, label_y + 16), _FONT_CV, 0.55, _WHITE, 1, cv2.LINE_AA)

    if overlay_info:
        lines = [
            f"{overlay_info.get('device_id', '')} | {overlay_info.get('location', '')}",
            f"Mode: {overlay_info.get('mode', 'recognition')}",
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        ]
        if _PIL_AVAILABLE and _pil_font_small is not None:
            for i, line in enumerate(lines):
                y = 6 + i * 20
                _put_unicode_text(out, line, (8, y), _pil_font_small, _GREEN, bg_color=_BLACK)
        else:
            for i, line in enumerate(lines):
                y = 22 + i * 22
                cv2.putText(out, line, (8, y), _FONT_CV, 0.5, _BLACK, 2, cv2.LINE_AA)
                cv2.putText(out, line, (8, y), _FONT_CV, 0.5, _GREEN, 1, cv2.LINE_AA)

    return out


def encode_jpeg(frame: np.ndarray, quality: int = 70) -> bytes:
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes()
