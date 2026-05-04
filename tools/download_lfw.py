"""
Download a subset of the LFW (Labeled Faces in the Wild) dataset.
Only downloads people with >= MIN_IMAGES_PER_PERSON images.

Usage:
    python tools/download_lfw.py [--output ./dataset/lfw] [--min-images 10] [--max-people 50]
"""

import argparse
import os
import shutil
import tarfile
import urllib.request

LFW_URL = "http://vis-www.cs.umass.edu/lfw/lfw.tgz"
LFW_FILENAME = "lfw.tgz"


def download_lfw(output_dir: str, min_images: int, max_people: int):
    os.makedirs(output_dir, exist_ok=True)
    tgz_path = os.path.join(output_dir, LFW_FILENAME)

    if not os.path.exists(tgz_path):
        print(f"Downloading LFW dataset from {LFW_URL}...")
        urllib.request.urlretrieve(LFW_URL, tgz_path)
        print(f"Downloaded to {tgz_path}")
    else:
        print(f"Archive already exists: {tgz_path}")

    print("Extracting...")
    with tarfile.open(tgz_path, "r:gz") as tar:
        tar.extractall(output_dir)

    lfw_dir = os.path.join(output_dir, "lfw")
    if not os.path.isdir(lfw_dir):
        print(f"ERROR: Expected directory {lfw_dir} not found after extraction")
        return

    people = []
    for person_name in sorted(os.listdir(lfw_dir)):
        person_dir = os.path.join(lfw_dir, person_name)
        if not os.path.isdir(person_dir):
            continue
        img_count = len([
            f for f in os.listdir(person_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ])
        if img_count >= min_images:
            people.append((person_name, img_count))

    people.sort(key=lambda x: x[1], reverse=True)
    selected = people[:max_people]

    print(f"\nFound {len(people)} people with >= {min_images} images")
    print(f"Selecting top {len(selected)} people:\n")

    final_dir = os.path.join(output_dir, "lfw_subset")
    os.makedirs(final_dir, exist_ok=True)

    for name, count in selected:
        src = os.path.join(lfw_dir, name)
        dst = os.path.join(final_dir, name)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"  {name}: {count} images")

    shutil.rmtree(lfw_dir)
    if os.path.exists(tgz_path):
        os.remove(tgz_path)

    print(f"\nDone! {len(selected)} people saved to {final_dir}")
    print(f"Total images: {sum(c for _, c in selected)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download LFW dataset subset")
    parser.add_argument("--output", default="./dataset", help="Output directory")
    parser.add_argument("--min-images", type=int, default=10, help="Minimum images per person")
    parser.add_argument("--max-people", type=int, default=50, help="Max number of people")
    args = parser.parse_args()
    download_lfw(args.output, args.min_images, args.max_people)
