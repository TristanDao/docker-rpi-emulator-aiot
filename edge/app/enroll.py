"""
Enroll a user's face from the edge camera.

Usage:
    docker compose exec edge python -m app.enroll --user-id 5
    docker compose exec edge python -m app.enroll --user-id 5 --samples 20 --timeout 90
"""

import argparse
import asyncio
import logging
import sys

from app import api_client
from app.config import DEVICE_ID, ENROLL_SAMPLES, ENROLL_TIMEOUT
from app.enroller import EnrollmentSession

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("enroll")


async def run(user_id: int, samples: int, timeout: int) -> int:
    logger.info("=== Face Enrollment (Edge Camera) ===")
    logger.info("User ID: %d | Samples: %d | Timeout: %ds", user_id, samples, timeout)

    user = await api_client.fetch_user(user_id)
    if user is None:
        logger.error("User %d not found on server. Aborting.", user_id)
        return 1

    logger.info(
        "Enrolling: %s (student_id=%s)", user["full_name"], user["student_id"],
    )

    session = EnrollmentSession(target_samples=samples, timeout=timeout)
    logger.info("Stand in front of the camera. Capturing %d samples...", samples)

    success = session.capture()
    collected = session.count

    if collected == 0:
        logger.error("No face samples captured. Aborting.")
        return 1

    if not success:
        logger.warning(
            "Only captured %d/%d samples. Sending what we have...",
            collected, samples,
        )

    logger.info("Sending %d embeddings to server...", collected)
    result = await api_client.send_enrollment(user_id, session.samples, DEVICE_ID)

    if result is None:
        logger.error("Failed to send enrollment to server.")
        return 1

    logger.info(
        "Enrollment complete: %d/%d saved (rate: %.0f%%) — status: %s",
        result["success_count"],
        result["total"],
        result["success_rate"] * 100,
        result["status"],
    )

    if result.get("errors"):
        for err in result["errors"]:
            logger.warning("  Sample %d: %s", err.get("index", "?"), err.get("reason"))

    return 0


def main():
    parser = argparse.ArgumentParser(description="Enroll face from edge camera")
    parser.add_argument("--user-id", type=int, required=True, help="User ID to enroll")
    parser.add_argument("--samples", type=int, default=ENROLL_SAMPLES, help="Number of samples")
    parser.add_argument("--timeout", type=int, default=ENROLL_TIMEOUT, help="Timeout in seconds")
    args = parser.parse_args()

    exit_code = asyncio.run(run(args.user_id, args.samples, args.timeout))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
