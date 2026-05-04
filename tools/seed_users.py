"""
Seed test users into the database via the server API.
Reads person directories from the dataset folder and creates users.

Usage:
    python tools/seed_users.py [--dataset ./dataset/lfw_subset] [--server http://localhost:8000]
"""

import argparse
import os

import requests


def seed_users(dataset_path: str, server_url: str):
    if not os.path.isdir(dataset_path):
        print(f"ERROR: Dataset directory not found: {dataset_path}")
        return

    persons = sorted([
        d for d in os.listdir(dataset_path)
        if os.path.isdir(os.path.join(dataset_path, d))
    ])

    if not persons:
        print(f"No subdirectories found in {dataset_path}")
        return

    print(f"Seeding {len(persons)} users from {dataset_path}\n")

    created = 0
    skipped = 0

    for person in persons:
        student_id = person.replace(" ", "_")
        full_name = person.replace("_", " ")

        check = requests.get(f"{server_url}/api/users", params={"student_id": student_id})
        if check.status_code == 200 and check.json():
            print(f"  SKIP: {student_id} (already exists)")
            skipped += 1
            continue

        payload = {
            "student_id": student_id,
            "full_name": full_name,
            "role": "student",
        }
        resp = requests.post(f"{server_url}/api/users", json=payload)

        if resp.status_code == 201:
            print(f"  OK: {student_id} -> id={resp.json()['id']}")
            created += 1
        else:
            print(f"  FAIL: {student_id} -> {resp.status_code}: {resp.text}")

    print(f"\nDone! Created: {created}, Skipped: {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed test users from dataset directories")
    parser.add_argument("--dataset", default="./dataset/lfw_subset", help="Path to dataset")
    parser.add_argument("--server", default="http://localhost:8000", help="Server URL")
    args = parser.parse_args()
    seed_users(args.dataset, args.server)
