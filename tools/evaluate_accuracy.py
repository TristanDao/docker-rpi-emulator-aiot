"""
Evaluate face recognition accuracy using a dataset.
Splits each person's images into train (80%) and test (20%),
enrolls with train set, then tests recognition accuracy.

Usage:
    python tools/evaluate_accuracy.py [--dataset ./dataset/lfw_subset] [--threshold 0.5]
"""

import argparse
import os
import random

import cv2
import face_recognition
import numpy as np


def load_dataset(dataset_path: str, train_ratio: float = 0.8):
    train_data = {}
    test_data = {}

    persons = sorted([
        d for d in os.listdir(dataset_path)
        if os.path.isdir(os.path.join(dataset_path, d))
    ])

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


def evaluate(dataset_path: str, threshold: float):
    print(f"Loading dataset from {dataset_path}...")
    train_data, test_data = load_dataset(dataset_path)
    print(f"Persons: {len(train_data)} (with >= 5 images)")

    known_encodings = []
    known_labels = []

    print("\nEnrolling (extracting embeddings from train set)...")
    for person, paths in train_data.items():
        encs = extract_encodings(paths)
        for enc in encs:
            known_encodings.append(enc)
            known_labels.append(person)
        print(f"  {person}: {len(encs)}/{len(paths)} train images")

    print(f"\nTotal enrolled embeddings: {len(known_encodings)}")

    if not known_encodings:
        print("ERROR: No embeddings extracted")
        return

    tp = 0
    fp = 0
    fn = 0
    total_tests = 0

    print("\nTesting recognition accuracy...")
    for person, paths in test_data.items():
        test_encs = extract_encodings(paths)
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

    accuracy = tp / total_tests if total_tests > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print(f"\n{'='*50}")
    print(f"EVALUATION RESULTS")
    print(f"{'='*50}")
    print(f"Threshold     : {threshold}")
    print(f"Total tests   : {total_tests}")
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
    args = parser.parse_args()

    random.seed(42)
    evaluate(args.dataset, args.threshold)
