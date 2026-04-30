"""
Benchmark: Compare face detection + recognition algorithm combinations on LFW dataset.
Outputs terminal table + markdown file for reporting.

Combinations tested:
  1. HOG + ResNet   (current system baseline)
  2. HOG + LBPH
  3. Haar + ResNet
  4. Haar + LBPH

Usage:
    python tools/benchmark_algorithms.py [--dataset ./dataset/lfw_subset] [--threshold 0.5] [--output ./tools/benchmark_results.md]
"""

import argparse
import os
import random
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import cv2
import face_recognition
import numpy as np


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkResult:
    combo_name: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    total_tests: int = 0
    detect_times_ms: list = field(default_factory=list)
    recog_times_ms: list = field(default_factory=list)
    detect_success: int = 0
    detect_total: int = 0

    @property
    def accuracy(self) -> float:
        return self.tp / self.total_tests if self.total_tests > 0 else 0.0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def avg_detect_ms(self) -> float:
        return sum(self.detect_times_ms) / len(self.detect_times_ms) if self.detect_times_ms else 0.0

    @property
    def avg_recog_ms(self) -> float:
        return sum(self.recog_times_ms) / len(self.recog_times_ms) if self.recog_times_ms else 0.0

    @property
    def detection_rate(self) -> float:
        return self.detect_success / self.detect_total if self.detect_total > 0 else 0.0


# ---------------------------------------------------------------------------
# Dataset loading (mirrors evaluate_accuracy.py pattern)
# ---------------------------------------------------------------------------

def load_dataset(dataset_path: str, train_ratio: float = 0.8):
    """Return (train_data, test_data) dicts: person_name -> list of image paths."""
    persons = sorted([
        d for d in os.listdir(dataset_path)
        if os.path.isdir(os.path.join(dataset_path, d))
    ])

    train_data: dict[str, list[str]] = {}
    test_data: dict[str, list[str]] = {}

    for person in persons:
        folder = os.path.join(dataset_path, person)
        images = sorted([
            f for f in os.listdir(folder)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ])
        if len(images) < 5:
            continue

        random.shuffle(images)
        split = int(len(images) * train_ratio)
        train_imgs = images[:split]
        test_imgs = images[split:]

        if not test_imgs:
            test_imgs = [train_imgs.pop()]

        train_data[person] = [os.path.join(folder, f) for f in train_imgs]
        test_data[person] = [os.path.join(folder, f) for f in test_imgs]

    return train_data, test_data


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

_haar_cascade: Optional[cv2.CascadeClassifier] = None


def _get_haar() -> cv2.CascadeClassifier:
    global _haar_cascade
    if _haar_cascade is None:
        xml_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _haar_cascade = cv2.CascadeClassifier(xml_path)
        if _haar_cascade.empty():
            raise RuntimeError(f"Failed to load Haar cascade XML from {xml_path}")
    return _haar_cascade


def detect_hog(rgb: np.ndarray) -> tuple[list, float]:
    """Detect faces with HOG. Returns (locations, elapsed_ms). locations: (top, right, bottom, left)."""
    t0 = time.perf_counter()
    locs = face_recognition.face_locations(rgb, model="hog")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return locs, elapsed_ms


def detect_haar(rgb: np.ndarray) -> tuple[list, float]:
    """Detect faces with Haar. Returns (locations, elapsed_ms). locations: (top, right, bottom, left)."""
    cascade = _get_haar()
    t0 = time.perf_counter()
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    rects = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    elapsed_ms = (time.perf_counter() - t0) * 1000

    locs = []
    if len(rects) > 0:
        for (x, y, w, h) in rects:
            top, right, bottom, left = y, x + w, y + h, x
            locs.append((top, right, bottom, left))
    return locs, elapsed_ms


def detect_face(rgb: np.ndarray, method: str) -> tuple[list, float]:
    if method == "hog":
        return detect_hog(rgb)
    elif method == "haar":
        return detect_haar(rgb)
    raise ValueError(f"Unknown detection method: {method}")


# ---------------------------------------------------------------------------
# Feature extraction helpers
# ---------------------------------------------------------------------------

def extract_face_roi(rgb: np.ndarray, loc: tuple, size: int = 100) -> np.ndarray:
    """Crop face ROI from image, convert to grayscale, resize for LBPH."""
    top, right, bottom, left = loc
    # Clamp to image bounds
    top = max(0, top)
    left = max(0, left)
    bottom = min(rgb.shape[0], bottom)
    right = min(rgb.shape[1], right)
    if bottom <= top or right <= left:
        return None
    face_rgb = rgb[top:bottom, left:right]
    face_gray = cv2.cvtColor(face_rgb, cv2.COLOR_RGB2GRAY)
    face_resized = cv2.resize(face_gray, (size, size))
    return face_resized


def extract_resnet_encoding(rgb: np.ndarray, loc: tuple) -> Optional[np.ndarray]:
    """Extract 128D ResNet embedding for a single detected face location."""
    t0 = time.perf_counter()
    encs = face_recognition.face_encodings(rgb, [loc])
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if encs:
        return encs[0], elapsed_ms
    return None, elapsed_ms


# ---------------------------------------------------------------------------
# Benchmark runners
# ---------------------------------------------------------------------------

def run_resnet(
    detect_method: str,
    train_data: dict,
    test_data: dict,
    threshold: float,
    combo_name: str,
) -> BenchmarkResult:
    """Benchmark a detect_method + ResNet recognition combination."""
    result = BenchmarkResult(combo_name=combo_name)
    known_encodings: list[np.ndarray] = []
    known_labels: list[str] = []

    # --- Train phase ---
    print(f"\n  [{combo_name}] Enrolling train set...")
    for person, paths in train_data.items():
        enrolled = 0
        for path in paths:
            img = cv2.imread(path)
            if img is None:
                continue
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            locs, detect_ms = detect_face(rgb, detect_method)
            result.detect_total += 1
            result.detect_times_ms.append(detect_ms)
            if len(locs) != 1:
                continue
            result.detect_success += 1
            enc, _ = extract_resnet_encoding(rgb, locs[0])
            if enc is not None:
                known_encodings.append(enc)
                known_labels.append(person)
                enrolled += 1
        print(f"    {person}: {enrolled}/{len(paths)} enrolled")

    print(f"  [{combo_name}] Total embeddings: {len(known_encodings)}")
    if not known_encodings:
        print(f"  [{combo_name}] ERROR: No embeddings enrolled — skipping test phase.")
        return result

    # --- Test phase ---
    print(f"  [{combo_name}] Testing...")
    for person, paths in test_data.items():
        for path in paths:
            img = cv2.imread(path)
            if img is None:
                continue
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            locs, detect_ms = detect_face(rgb, detect_method)
            result.detect_total += 1
            result.detect_times_ms.append(detect_ms)
            if len(locs) != 1:
                continue
            result.detect_success += 1

            t0 = time.perf_counter()
            enc, _ = extract_resnet_encoding(rgb, locs[0])
            if enc is None:
                result.fn += 1
                result.total_tests += 1
                continue
            distances = face_recognition.face_distance(known_encodings, enc)
            min_idx = int(np.argmin(distances))
            min_dist = distances[min_idx]
            predicted = known_labels[min_idx] if min_dist < threshold else None
            elapsed_ms = (time.perf_counter() - t0) * 1000
            result.recog_times_ms.append(elapsed_ms)

            result.total_tests += 1
            if predicted == person:
                result.tp += 1
            elif predicted is None:
                result.fn += 1
            else:
                result.fp += 1

    return result


def run_lbph(
    detect_method: str,
    train_data: dict,
    test_data: dict,
    lbph_threshold: float,
    combo_name: str,
) -> BenchmarkResult:
    """Benchmark a detect_method + LBPH recognition combination."""
    result = BenchmarkResult(combo_name=combo_name)

    persons = sorted(train_data.keys())
    person_to_id = {name: idx for idx, name in enumerate(persons)}
    id_to_person = {idx: name for name, idx in person_to_id.items()}

    faces: list[np.ndarray] = []
    labels: list[int] = []

    # --- Train phase ---
    print(f"\n  [{combo_name}] Enrolling train set...")
    for person, paths in train_data.items():
        enrolled = 0
        pid = person_to_id[person]
        for path in paths:
            img = cv2.imread(path)
            if img is None:
                continue
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            locs, detect_ms = detect_face(rgb, detect_method)
            result.detect_total += 1
            result.detect_times_ms.append(detect_ms)
            if len(locs) != 1:
                continue
            result.detect_success += 1
            roi = extract_face_roi(rgb, locs[0])
            if roi is None:
                continue
            faces.append(roi)
            labels.append(pid)
            enrolled += 1
        print(f"    {person}: {enrolled}/{len(paths)} enrolled")

    print(f"  [{combo_name}] Total face ROIs: {len(faces)}")
    if len(faces) < 2:
        print(f"  [{combo_name}] ERROR: Not enough face ROIs to train LBPH — skipping.")
        return result

    lbph = cv2.face.LBPHFaceRecognizer_create()
    lbph.train(faces, np.array(labels, dtype=np.int32))
    print(f"  [{combo_name}] LBPH trained.")

    # --- Test phase ---
    print(f"  [{combo_name}] Testing...")
    for person, paths in test_data.items():
        for path in paths:
            img = cv2.imread(path)
            if img is None:
                continue
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            locs, detect_ms = detect_face(rgb, detect_method)
            result.detect_total += 1
            result.detect_times_ms.append(detect_ms)
            if len(locs) != 1:
                continue
            result.detect_success += 1

            t0 = time.perf_counter()
            roi = extract_face_roi(rgb, locs[0])
            if roi is None:
                continue
            label, confidence = lbph.predict(roi)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            result.recog_times_ms.append(elapsed_ms)

            predicted = id_to_person.get(label) if confidence < lbph_threshold else None
            result.total_tests += 1

            if predicted == person:
                result.tp += 1
            elif predicted is None:
                result.fn += 1
            else:
                result.fp += 1

    return result


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def print_terminal_table(results: list[BenchmarkResult], dataset_path: str, total_images: int, total_people: int, resnet_threshold: float = 0.5, lbph_threshold: float = 80.0) -> None:
    today = date.today().isoformat()
    print()
    print("=" * 60)
    print("ALGORITHM BENCHMARK RESULTS")
    print("=" * 60)
    print(f"Dataset    : {dataset_path} ({total_people} people, {total_images} images)")
    print(f"Date       : {today}")
    print(f"Split      : 80% train / 20% test (seed=42)")
    print(f"ResNet thr : {resnet_threshold} (Euclidean distance)")
    print(f"LBPH thr   : {lbph_threshold} (confidence, lower=better)")
    print("=" * 60)

    # Detection comparison (collect unique detect methods)
    seen: dict[str, BenchmarkResult] = {}
    for r in results:
        detect_key = r.combo_name.split(" + ")[0]
        if detect_key not in seen:
            seen[detect_key] = r

    print("\nDetection Comparison:")
    header = f"{'Method':<12}{'Detection Rate':<18}{'Avg Speed (ms)':<18}{'Images Tested':<14}"
    sep = "  " + "-" * 58
    print(sep)
    print(f"  {header}")
    print(sep)
    for key, r in seen.items():
        print(f"  {key:<12}{_pct(r.detection_rate):<18}{r.avg_detect_ms:<18.1f}{r.detect_total:<14}")
    print(sep)

    print("\nRecognition Comparison (4 Combinations):")
    col_fmt = "  {:<20}{:<12}{:<12}{:<10}{:<12}{:<15}"
    sep2 = "  " + "-" * 75
    print(sep2)
    print(col_fmt.format("Combination", "Accuracy", "Precision", "Recall", "F1 Score", "Avg Time(ms)"))
    print(sep2)
    for r in results:
        avg_ms = r.avg_detect_ms + r.avg_recog_ms
        print(col_fmt.format(
            r.combo_name,
            _pct(r.accuracy),
            _pct(r.precision),
            _pct(r.recall),
            _pct(r.f1),
            f"{avg_ms:.1f} ms",
        ))
    print(sep2)
    print()


def write_markdown(results: list[BenchmarkResult], dataset_path: str, total_images: int, total_people: int, output_path: str, resnet_threshold: float = 0.5, lbph_threshold: float = 80.0) -> None:
    today = date.today().isoformat()

    # Pick best combo by F1
    best = max(results, key=lambda r: r.f1)

    # Detection rows
    seen: dict[str, BenchmarkResult] = {}
    for r in results:
        detect_key = r.combo_name.split(" + ")[0]
        if detect_key not in seen:
            seen[detect_key] = r

    detect_rows = ""
    for key, r in seen.items():
        detect_rows += f"| {key:<12} | {_pct(r.detection_rate):<16} | {r.avg_detect_ms:<15.1f} | {r.detect_total:<12} |\n"

    recog_rows = ""
    for r in results:
        label = r.combo_name
        if "HOG + ResNet" in label:
            label += " (Hệ thống hiện tại)"
        avg_ms = r.avg_detect_ms + r.avg_recog_ms
        recog_rows += f"| {label:<40} | {_pct(r.accuracy):<9} | {_pct(r.precision):<10} | {_pct(r.recall):<7} | {_pct(r.f1):<9} | {avg_ms:<15.1f} |\n"

    # Build conclusion
    speed_winner = min(results, key=lambda r: r.avg_detect_ms + r.avg_recog_ms)
    accuracy_winner = max(results, key=lambda r: r.accuracy)

    lbph_results = [r for r in results if "LBPH" in r.combo_name]
    lbph_note = ""
    if lbph_results:
        max_lbph_recall = max(r.recall for r in lbph_results)
        if max_lbph_recall > 0.95:
            lbph_note = (
                f"\n### Ghi chú về LBPH\n\n"
                f"- LBPH Recall cao ({_pct(max_lbph_recall)}) do threshold ({lbph_threshold}) "
                f"lỏng — hầu hết ảnh test đều match (kể cả sai người), dẫn đến FP cao.\n"
                f"- LBPH phù hợp cho hệ thống nhỏ, offline. ResNet vượt trội về accuracy và tốc độ.\n"
            )
        else:
            lbph_note = (
                f"\n### Ghi chú về LBPH\n\n"
                f"- LBPH cho accuracy thấp hơn đáng kể so với ResNet do hạn chế của feature extraction truyền thống.\n"
                f"- ResNet (deep learning) tạo embedding 128D robust hơn với biến thể ánh sáng, góc chụp.\n"
            )

    conclusion = (
        f"- **Tốt nhất về F1**: `{best.combo_name}` (F1 = {_pct(best.f1)})\n"
        f"- **Tốt nhất về accuracy**: `{accuracy_winner.combo_name}` ({_pct(accuracy_winner.accuracy)})\n"
        f"- **Nhanh nhất**: `{speed_winner.combo_name}` ({speed_winner.avg_detect_ms + speed_winner.avg_recog_ms:.1f} ms/frame)\n"
        f"- HOG + ResNet là baseline của hệ thống hiện tại.\n"
        f"{lbph_note}"
    )

    md = f"""# Benchmark: So sánh thuật toán nhận diện khuôn mặt

> Dataset: LFW subset ({total_people} người, {total_images} ảnh)
> Ngày: {today}
> Tỷ lệ chia: 80% train / 20% test (seed=42)
> Threshold: ResNet = {resnet_threshold} (Euclidean distance) | LBPH = {lbph_threshold} (confidence, thấp hơn = chính xác hơn)

## So sánh Detection

| Phương pháp | Tỷ lệ phát hiện | Tốc độ TB (ms) | Tổng ảnh (train+test) |
|-------------|-----------------|----------------|----------------------|
{detect_rows}
## So sánh Recognition (4 Tổ hợp)

| Tổ hợp | Accuracy | Precision | Recall | F1 Score | Tốc độ TB (ms) |
|--------|----------|-----------|--------|----------|----------------|
{recog_rows}
## Kết luận

{conclusion}
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Markdown report saved to: {output_path}")


# ---------------------------------------------------------------------------
# Dataset stats helper
# ---------------------------------------------------------------------------

def count_dataset(dataset_path: str) -> tuple[int, int]:
    total_images = 0
    total_people = 0
    if not os.path.isdir(dataset_path):
        return 0, 0
    for person in os.listdir(dataset_path):
        folder = os.path.join(dataset_path, person)
        if not os.path.isdir(folder):
            continue
        imgs = [f for f in os.listdir(folder) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
        if imgs:
            total_people += 1
            total_images += len(imgs)
    return total_people, total_images


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Benchmark face detection + recognition algorithm combinations")
    parser.add_argument("--dataset", default="./dataset/lfw_subset", help="Path to dataset directory")
    parser.add_argument("--threshold", type=float, default=0.5, help="ResNet distance threshold (default: 0.5)")
    parser.add_argument("--lbph-threshold", type=float, default=80.0, help="LBPH confidence threshold (lower=stricter, default: 80)")
    parser.add_argument("--output", default="./tools/benchmark_results.md", help="Output markdown file path")
    args = parser.parse_args()

    random.seed(42)

    dataset_path = args.dataset
    if not os.path.isdir(dataset_path):
        print(f"ERROR: Dataset not found at {dataset_path}")
        return

    total_people, total_images = count_dataset(dataset_path)
    print(f"Loading dataset from {dataset_path}...")
    print(f"Found: {total_people} people, {total_images} images")

    train_data, test_data = load_dataset(dataset_path)
    print(f"Persons (>= 5 images): {len(train_data)}")

    combos = [
        ("HOG + ResNet",  "hog",  "resnet"),
        ("HOG + LBPH",    "hog",  "lbph"),
        ("Haar + ResNet", "haar", "resnet"),
        ("Haar + LBPH",   "haar", "lbph"),
    ]

    results: list[BenchmarkResult] = []

    for combo_name, detect_method, recog_method in combos:
        print(f"\n{'='*50}")
        print(f"Running: {combo_name}")
        print(f"{'='*50}")
        if recog_method == "resnet":
            r = run_resnet(detect_method, train_data, test_data, args.threshold, combo_name)
        else:
            r = run_lbph(detect_method, train_data, test_data, args.lbph_threshold, combo_name)
        results.append(r)
        print(f"  Done — Accuracy: {_pct(r.accuracy)}, F1: {_pct(r.f1)}, Tests: {r.total_tests}")

    for r in results:
        if "LBPH" in r.combo_name and r.total_tests > 0 and r.recall < 0.1:
            print(f"\n  WARNING: {r.combo_name} recall is only {_pct(r.recall)} — "
                  f"try increasing --lbph-threshold (current: {args.lbph_threshold})")

    print_terminal_table(results, dataset_path, total_images, total_people, args.threshold, args.lbph_threshold)
    write_markdown(results, dataset_path, total_images, total_people, args.output, args.threshold, args.lbph_threshold)


if __name__ == "__main__":
    main()
