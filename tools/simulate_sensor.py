"""Synthetic sensor simulator for API demonstrations; never farm measurements."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def build_parser() -> argparse.ArgumentParser:
    """Create Windows-friendly simulator options without accepting secrets as flags."""
    parser = argparse.ArgumentParser(
        description="Send clearly marked synthetic readings to a local demo backend."
    )
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:5000", help="Backend address"
    )
    parser.add_argument("--room", default="Room 1")
    parser.add_argument("--device-id", default="SYNTHETIC-TEST-SENSOR")
    parser.add_argument(
        "--interval", type=float, default=5.0, help="Seconds between examples"
    )
    parser.add_argument(
        "--count", type=int, default=1, help="Number of example readings"
    )
    parser.add_argument(
        "--inject", choices=("none", "spike", "dry", "offline"), default="none"
    )
    return parser


def main() -> int:
    """Send synthetic readings or remain silent for the offline-sensor scenario."""
    args = build_parser().parse_args()
    if args.interval < 0 or args.count < 1:
        raise SystemExit(
            "Interval must be non-negative and count must be at least one."
        )
    api_key = os.getenv("API_KEY", "")
    randomizer = random.Random(1742)
    for index in range(args.count):
        if args.inject == "offline":
            print("Synthetic offline scenario: no sensor request sent.")
        else:
            angle = datetime.now().hour * math.tau / 24
            temperature = round(
                24.0 + math.sin(angle) * 1.1 + randomizer.uniform(-0.25, 0.25), 1
            )
            humidity = round(
                85.0 + math.cos(angle) * 2.0 + randomizer.uniform(-0.6, 0.6), 1
            )
            if args.inject == "spike":
                temperature = 28.0
            elif args.inject == "dry":
                humidity = 76.0
            payload = {
                "temperature": temperature,
                "humidity": humidity,
                "room": args.room,
                "device_id": args.device_id,
                "synthetic": True,
            }
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["X-API-Key"] = api_key
            request = Request(
                f"{args.base_url.rstrip('/')}/sensor",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urlopen(request, timeout=10) as response:
                    print(
                        f"Synthetic example {index + 1}: backend response {response.status}."
                    )
            except (HTTPError, URLError, TimeoutError):
                print(
                    "Could not reach the backend. Check that the demo is running and try again."
                )
                return 1
        if index + 1 < args.count:
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
