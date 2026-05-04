"""
Download LFW dataset using sklearn (uses a different mirror than the direct URL).
Saves images in the expected folder structure: dataset/lfw_subset/{person_name}/img_001.jpg

Usage:
    python tools/download_lfw_sklearn.py [--output ./dataset/lfw_subset] [--min-images 10] [--max-people 15]
"""

import argparse
import os

import cv2
import numpy as np
from sklearn.datasets import fetch_lfw_people


def download_and_save(output_dir: str, min_images: int, max_people: int):
    print("Downloading LFW via sklearn (may take a few minutes on first run)...")
    lfw = fetch_lfw_people(min_faces_per_person=min_images, resize=1.0)

    images = lfw.images
    labels = lfw.target
    names = lfw.target_names

    print(f"Total images: {len(images)}")
    print(f"People with >= {min_images} images: {len(names)}")

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
            img_uint8 = (img * 255).astype(np.uint8) if img.max() <= 1.0 else img.astype(np.uint8)

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
    parser = argparse.ArgumentParser(description="Download LFW via sklearn")
    parser.add_argument("--output", default="./dataset/lfw_subset")
    parser.add_argument("--min-images", type=int, default=10)
    parser.add_argument("--max-people", type=int, default=15)
    args = parser.parse_args()
    download_and_save(args.output, args.min_images, args.max_people)
