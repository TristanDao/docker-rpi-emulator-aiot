"""
Generate a JWT token for a device (for testing API calls manually).

Usage:
    python tools/generate_token.py [--device-id pi_emulator_01] [--secret <jwt-secret>]
"""

import argparse
from datetime import datetime, timedelta, timezone

from jose import jwt


def generate(device_id: str, secret: str, algorithm: str = "HS256"):
    payload = {
        "sub": device_id,
        "iss": "face-attendance-edge",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
    }
    token = jwt.encode(payload, secret, algorithm=algorithm)
    print(f"Device: {device_id}")
    print(f"Token:  {token}")
    print(f"\nUsage:")
    print(f'  curl -H "Authorization: Bearer {token}" http://localhost:8000/api/embeddings/sync')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate JWT for device")
    parser.add_argument("--device-id", default="pi_emulator_01")
    parser.add_argument("--secret", default="aiot-face-attendance-jwt-secret-2025")
    args = parser.parse_args()
    generate(args.device_id, args.secret)
