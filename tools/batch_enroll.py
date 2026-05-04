"""
Batch enroll faces from a dataset directory into the server.
Each subdirectory represents one person (student_id = directory name).

Usage:
    python tools/batch_enroll.py [--dataset ./dataset/lfw_subset] [--server http://localhost:8000]
"""

import argparse
import os

import requests


def batch_enroll(dataset_path: str, server_url: str):
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

    print(f"\nBatch enrolling {len(persons)} people from {dataset_path}\n")

    total_ok = 0
    total_fail = 0

    for idx, person in enumerate(persons):
        student_id = person.replace(" ", "_")
        folder = os.path.join(dataset_path, person)
        img_files = [
            f for f in os.listdir(folder)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ]

        if not img_files:
            print(f"[{idx+1}/{len(persons)}] SKIP {student_id}: no images")
            continue

        r = requests.get(f"{server_url}/api/users", params={"student_id": student_id})
        if r.status_code != 200 or not r.json():
            print(f"[{idx+1}/{len(persons)}] FAIL {student_id}: user not found in DB")
            total_fail += 1
            continue

        user_id = r.json()[0]["id"]

        status_r = requests.get(f"{server_url}/api/users/{user_id}/enrollment-status")
        if status_r.status_code == 200 and status_r.json().get("is_sufficient"):
            print(f"[{idx+1}/{len(persons)}] SKIP {student_id}: already enrolled ({status_r.json()['sample_count']} samples)")
            continue

        files = []
        for img_file in img_files:
            path = os.path.join(folder, img_file)
            files.append(("files", (img_file, open(path, "rb"), "image/jpeg")))

        try:
            result = requests.post(
                f"{server_url}/api/enroll/upload",
                params={"user_id": user_id},
                files=files,
            ).json()

            ok = result["success_count"]
            total = result["total"]
            rate = result["success_rate"] * 100
            icon = "OK" if ok >= total * 0.8 else "WARN"

            print(f"[{idx+1}/{len(persons)}] {icon} {student_id}: {ok}/{total} images ({rate:.0f}%)")

            for err in result.get("errors", []):
                print(f"   -> image {err['index']}: {err['reason']}")

            total_ok += 1
        except Exception as e:
            print(f"[{idx+1}/{len(persons)}] ERROR {student_id}: {e}")
            total_fail += 1
        finally:
            for _, file_tuple in files:
                file_tuple[1].close()

    print(f"\n{'='*50}")
    print(f"Done! Success: {total_ok}, Failed: {total_fail}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch enroll faces from dataset")
    parser.add_argument("--dataset", default="./dataset/lfw_subset", help="Path to dataset")
    parser.add_argument("--server", default="http://localhost:8000", help="Server URL")
    args = parser.parse_args()
    batch_enroll(args.dataset, args.server)
