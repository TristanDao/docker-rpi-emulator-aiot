"""
Download LFW using sklearn's mirror. Two output modes:

- cropped (default): grayscale face crops saved as img_001.jpg (sklearn slice + resize).
- raw: copy original funneled/non-funneled JPEGs from the cached archive (every file on disk).

LFW is long-tailed: many identities have only one photo in the release; that is expected.

Usage:
    python tools/download_lfw_sklearn.py --mode raw --output ./dataset/lfw_raw --min-images 0 --max-people 0
    python tools/download_lfw_sklearn.py --mode cropped --output ./dataset/lfw_cropped --min-images 0 --max-people 0
"""

from __future__ import annotations

import argparse
import os
import shutil

import cv2
import numpy as np
from sklearn.datasets import fetch_lfw_people, get_data_home


def _ensure_archives_downloaded(*, funneled: bool) -> str:
    fetch_lfw_people(
        min_faces_per_person=0,
        resize=1.0,
        funneled=funneled,
        download_if_missing=True,
    )
    sub = "lfw_funneled" if funneled else "lfw"
    return os.path.join(get_data_home(), "lfw_home", sub)


def copy_raw_jpegs(
    output_dir: str,
    min_images: int,
    max_people: int,
    *,
    funneled: bool,
    quiet: bool,
) -> None:
    src_root = _ensure_archives_downloaded(funneled=funneled)
    if not os.path.isdir(src_root):
        raise FileNotFoundError(f"Expected LFW folder missing: {src_root}")

    candidates: list[tuple[str, str, list[str]]] = []
    for entry in sorted(os.listdir(src_root)):
        folder = os.path.join(src_root, entry)
        if not os.path.isdir(folder):
            continue
        jpgs = sorted(
            f
            for f in os.listdir(folder)
            if f.lower().endswith((".jpg", ".jpeg"))
        )
        if len(jpgs) < min_images:
            continue
        candidates.append((entry, folder, jpgs))

    if max_people <= 0:
        selected = candidates
        print(f"Copying JPEGs for all {len(selected)} people under {src_root}\n")
    else:
        selected = candidates[:max_people]
        print(f"Copying JPEGs for {len(selected)} people (alphabetical order)\n")

    os.makedirs(output_dir, exist_ok=True)
    total = 0
    for safe_name, folder, jpgs in selected:
        out_person = os.path.join(output_dir, safe_name)
        os.makedirs(out_person, exist_ok=True)
        for name in jpgs:
            shutil.copy2(os.path.join(folder, name), os.path.join(out_person, name))
            total += 1
        if not quiet:
            print(f"  {safe_name}: {len(jpgs)} JPEGs copied")

    print(f"\nDone! {total} JPEGs for {len(selected)} people copied to {output_dir}")


def download_and_save_cropped(output_dir: str, min_images: int, max_people: int) -> None:
    print("Downloading LFW via sklearn (may take a few minutes on first run)...")
    lfw = fetch_lfw_people(min_faces_per_person=min_images, resize=1.0)

    images = lfw.images
    labels = lfw.target
    names = lfw.target_names

    print(f"Total images: {len(images)}")
    print(f"People with >= {min_images} images: {len(names)}")

    if max_people <= 0:
        selected_names = names
        print(f"Saving all {len(selected_names)} people\n")
    else:
        selected_names = names[:max_people]
        print(f"Selecting top {len(selected_names)} people\n")

    os.makedirs(output_dir, exist_ok=True)
    total_saved = 0

    for person_idx, person_name in enumerate(selected_names):
        mask = labels == person_idx
        person_images = images[mask]

        safe_name = person_name.replace(" ", "_")
        person_dir = os.path.join(output_dir, safe_name)
        os.makedirs(person_dir, exist_ok=True)

        for i, img in enumerate(person_images):
            img_uint8 = (
                (img * 255).astype(np.uint8)
                if img.max() <= 1.0
                else img.astype(np.uint8)
            )

            if len(img_uint8.shape) == 2:
                img_bgr = cv2.cvtColor(img_uint8, cv2.COLOR_GRAY2BGR)
            else:
                img_bgr = img_uint8

            filepath = os.path.join(person_dir, f"img_{i+1:03d}.jpg")
            cv2.imwrite(filepath, img_bgr)
            total_saved += 1

        print(f"  {safe_name}: {len(person_images)} images saved")

    print(f"\nDone! {total_saved} images for {len(selected_names)} people saved to {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download/export LFW via sklearn cache")
    parser.add_argument("--output", default="./dataset/lfw_subset")
    parser.add_argument(
        "--mode",
        choices=("cropped", "raw"),
        default="cropped",
        help="cropped = sklearn crops; raw = full JPEG copies from sklearn lfw_home.",
    )
    parser.add_argument(
        "--no-funneled",
        dest="funneled",
        action="store_false",
        help="Use lfw/ JPEGs instead of lfw_funneled/ (downloads lfw.tgz if missing).",
    )
    parser.set_defaults(funneled=True)
    parser.add_argument(
        "--min-images",
        type=int,
        default=10,
        help="Minimum images per identity (folders with fewer JPEGs skipped in raw mode; sklearn filter in cropped mode). Use 0 for everyone.",
    )
    parser.add_argument(
        "--max-people",
        type=int,
        default=15,
        help="Max identities; 0 or negative = all (alphabetically).",
    )
    parser.add_argument("--quiet", action="store_true", help="Fewer progress lines.")
    args = parser.parse_args()
    if args.mode == "raw":
        copy_raw_jpegs(
            args.output,
            args.min_images,
            args.max_people,
            funneled=args.funneled,
            quiet=args.quiet,
        )
    else:
        download_and_save_cropped(args.output, args.min_images, args.max_people)
