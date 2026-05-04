"""
Create a test video from dataset images for the edge emulator.
Picks random images from the dataset and stitches them into a video,
simulating people walking past a camera.

Usage:
    python tools/create_test_video.py [--dataset ./dataset/lfw_subset] [--output ./test_videos/classroom_demo.mp4]
"""

import argparse
import os
import random

import cv2
import numpy as np


def create_test_video(dataset_path: str, output_path: str, fps: int = 2,
                      frames_per_person: int = 5, target_size: tuple = (640, 480)):
    persons = sorted([
        d for d in os.listdir(dataset_path)
        if os.path.isdir(os.path.join(dataset_path, d))
    ])

    if not persons:
        print("No person directories found")
        return

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, fps, target_size)

    total_frames = 0
    selected = random.sample(persons, min(10, len(persons)))

    print(f"Creating test video with {len(selected)} people, {frames_per_person} frames each")
    print(f"FPS: {fps}, Resolution: {target_size}\n")

    for person in selected:
        folder = os.path.join(dataset_path, person)
        images = [f for f in os.listdir(folder) if f.lower().endswith((".jpg", ".jpeg", ".png"))]

        chosen = random.sample(images, min(frames_per_person, len(images)))

        for img_name in chosen:
            img = cv2.imread(os.path.join(folder, img_name))
            if img is None:
                continue

            h, w = img.shape[:2]
            scale = min(target_size[0] / w, target_size[1] / h)
            new_w, new_h = int(w * scale), int(h * scale)
            resized = cv2.resize(img, (new_w, new_h))

            canvas = np.zeros((target_size[1], target_size[0], 3), dtype=np.uint8)
            y_off = (target_size[1] - new_h) // 2
            x_off = (target_size[0] - new_w) // 2
            canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized

            writer.write(canvas)
            total_frames += 1

        for _ in range(fps):
            blank = np.zeros((target_size[1], target_size[0], 3), dtype=np.uint8)
            writer.write(blank)
            total_frames += 1

        print(f"  Added {len(chosen)} frames for {person}")

    writer.release()
    duration = total_frames / fps
    print(f"\nDone! Video saved: {output_path}")
    print(f"Total frames: {total_frames}, Duration: {duration:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create test video from dataset")
    parser.add_argument("--dataset", default="./dataset/lfw_subset")
    parser.add_argument("--output", default="./test_videos/classroom_demo.mp4")
    parser.add_argument("--fps", type=int, default=2)
    args = parser.parse_args()

    random.seed(42)
    create_test_video(args.dataset, args.output, fps=args.fps)
