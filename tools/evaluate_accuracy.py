"""
Evaluate face recognition accuracy using a dataset.
Splits each person's images into train and test subsets,
enrolls with train set, then tests recognition accuracy.

Identities need at least min_images_per_person photos to form a train/test split
(for example use 2 for nearly all of LFW; default 5 matches the older tutorial subset).

Usage:
    python tools/evaluate_accuracy.py --dataset ./dataset/lfw_full_raw --min-images-per-person 2
    python tools/evaluate_accuracy.py [--dataset ./dataset/lfw_subset] [--threshold 0.5]
"""

import argparse
import os
from random import Random

import cv2
import face_recognition
import numpy as np


def load_dataset(
    dataset_path: str,
    train_ratio: float,
    *,
    min_images_per_person: int,
    seed: int,
) -> tuple[dict[str, list[str]], dict[str, list[str]], int, int, int]:
    train_data = {}
    test_data = {}
    rnd = Random(seed)

    persons = sorted([
        d for d in os.listdir(dataset_path)
        if os.path.isdir(os.path.join(dataset_path, d))
    ])

    skipped = 0
    qualifying_image_total = 0
    for person in persons:
        folder = os.path.join(dataset_path, person)
        images = sorted([
            f for f in os.listdir(folder)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ])

        if len(images) < min_images_per_person:
            skipped += 1
            continue

        qualifying_image_total += len(images)

        rnd.shuffle(images)
        split = int(len(images) * train_ratio)
        train_imgs = images[:split]
        test_imgs = images[split:]

        if not train_imgs:
            skipped += 1
            continue

        if not test_imgs:
            test_imgs = [train_imgs.pop()]

        train_data[person] = [os.path.join(folder, f) for f in train_imgs]
        test_data[person] = [os.path.join(folder, f) for f in test_imgs]

    included = len(train_data)
    return train_data, test_data, included, skipped, qualifying_image_total


def extract_encodings(image_paths: list) -> list[np.ndarray]:
    encodings = []
    for path in image_paths:
        img = cv2.imread(path)
        if img is None:
            continue
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        locs = face_recognition.face_locations(rgb, model="hog")
        if len(locs) != 1:
            continue
        encs = face_recognition.face_encodings(rgb, locs)
        if encs:
            encodings.append(encs[0])
    return encodings


def evaluate(
    dataset_path: str,
    threshold: float,
    *,
    min_images_per_person: int,
    train_ratio: float,
    seed: int,
    verbose: bool,
) -> None:
    print(f"Loading dataset from {dataset_path}...")
    train_data, test_data, n_included, n_skipped, n_qualifying_images = load_dataset(
        dataset_path,
        train_ratio,
        min_images_per_person=min_images_per_person,
        seed=seed,
    )
    n_train_paths = sum(len(paths) for paths in train_data.values())
    n_test_paths = sum(len(paths) for paths in test_data.values())
    print(
        f"Qualifying folders: {n_included} identities, {n_qualifying_images} image files "
        f"(each folder has >= {min_images_per_person} images)."
    )
    print(
        f"After split (train_ratio={train_ratio}): "
        f"{n_train_paths} enroll image paths, {n_test_paths} probe image paths."
    )
    print(
        f"Skipped {n_skipped} folders (below min_images_per_person or could not split)."
    )

    known_encodings = []
    known_labels = []

    print("\nEnrolling (extracting embeddings from train set)...")
    enroll_print_step = max(1, len(train_data) // 20) if not verbose else 1
    for i, (person, paths) in enumerate(train_data.items()):
        encs = extract_encodings(paths)
        for enc in encs:
            known_encodings.append(enc)
            known_labels.append(person)
        if verbose or len(train_data) <= 40 or i % enroll_print_step == 0:
            print(f"  {person}: {len(encs)}/{len(paths)} train images")

    print(f"\nTotal enrolled embeddings: {len(known_encodings)}")

    if not known_encodings:
        print("ERROR: No embeddings extracted")
        return

    tp = 0
    fp = 0
    fn = 0
    total_tests = 0

    n_probe_identities = len(test_data)
    n_probe_image_paths = n_test_paths
    identities_with_probe_embedding: set[str] = set()

    print("\nTesting recognition accuracy...")
    for person, paths in test_data.items():
        test_encs = extract_encodings(paths)
        if test_encs:
            identities_with_probe_embedding.add(person)
        for enc in test_encs:
            distances = face_recognition.face_distance(known_encodings, enc)
            min_idx = int(np.argmin(distances))
            min_dist = distances[min_idx]

            predicted = known_labels[min_idx] if min_dist < threshold else None
            total_tests += 1

            if predicted == person:
                tp += 1
            elif predicted is None:
                fn += 1
            else:
                fp += 1

    n_skipped_probe_paths = n_probe_image_paths - total_tests

    accuracy = tp / total_tests if total_tests > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print(f"\n{'='*50}")
    print(f"EVALUATION RESULTS")
    print(f"{'='*50}")
    print(f"Threshold     : {threshold}")
    print(
        f"Probe scope   : {n_probe_identities} identities with probe paths; "
        f"{n_probe_image_paths} probe image files."
    )
    print(
        f"Total tests   : {total_tests} (= successful probe embeddings); "
        f"{len(identities_with_probe_embedding)} identities with >=1 successful probe; "
        f"{n_skipped_probe_paths} probe files yielded no embedding "
        f"(unread, 0 faces, or not exactly 1 HOG face)."
    )
    print(f"True Positive : {tp}")
    print(f"False Positive: {fp}")
    print(f"False Negative: {fn}")
    print(f"{'='*50}")
    print(f"Accuracy      : {accuracy:.4f} ({accuracy*100:.1f}%)")
    print(f"Precision     : {precision:.4f} ({precision*100:.1f}%)")
    print(f"Recall        : {recall:.4f} ({recall*100:.1f}%)")
    print(f"F1 Score      : {f1:.4f} ({f1*100:.1f}%)")
    print(f"{'='*50}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate face recognition accuracy")
    parser.add_argument("--dataset", default="./dataset/lfw_subset", help="Path to dataset")
    parser.add_argument("--threshold", type=float, default=0.5, help="Distance threshold")
    parser.add_argument(
        "--min-images-per-person",
        type=int,
        default=5,
        help=(
            "Minimum images per identity to enroll and probe (needs >= 2 for a train/test split; "
            "use 2 to include nearly all identities on full LFW)."
        ),
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.8,
        help="Fraction of each identity's images used for enrollment (rest for testing).",
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducible splits")
    parser.add_argument("--verbose", action="store_true", help="Print every enrollment line")
    args = parser.parse_args()

    if args.min_images_per_person < 2:
        parser.error("--min-images-per-person must be at least 2 (need hold-out probes).")

    if not (0 < args.train_ratio < 1):
        parser.error("--train-ratio must be between 0 and 1 (exclusive).")

    evaluate(
        args.dataset,
        args.threshold,
        min_images_per_person=args.min_images_per_person,
        train_ratio=args.train_ratio,
        seed=args.seed,
        verbose=args.verbose,
    )
