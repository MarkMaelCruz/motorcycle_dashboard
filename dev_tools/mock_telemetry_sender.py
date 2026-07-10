"""
mock_telemetry_sender.py
=========================
Stands in for raspberry_pi/serial_bridge.py when you don't have the
physical Pi/Arduino available (e.g. testing from GitHub Codespaces).

It POSTs realistic, changing telemetry to /telemetry at the same 10 Hz
rate serial_bridge.py uses, cycling through a simulated ride so you
can watch `riding_state` actually change over time instead of getting
one frozen value from a single curl command.

This does NOT replace real hardware testing before the system goes
back on the actual bike — it only lets you verify the JOB B pipeline
(feature engineering -> classification -> /stream -> dashboard badge)
end-to-end while you don't have the Pi.

USAGE
-----
    # against your local backend (Step 8 of README.md), run this in a
    # SECOND terminal while `python app.py` is running in the first:
    python dev_tools/mock_telemetry_sender.py

    # against the real deployed backend instead (be careful — this
    # overwrites whatever /latest currently shows for anyone else
    # watching the live dashboard):
    python dev_tools/mock_telemetry_sender.py --url https://motorcycle-telemetry-backend-112434217886.asia-southeast1.run.app/telemetry

    # stop any time with Ctrl+C
"""

import argparse
import math
import time
import sys

import requests

DEFAULT_URL = "http://localhost:8080/telemetry"
SEND_INTERVAL = 0.10  # seconds, matches serial_bridge.py's 10 Hz


def build_sample(t: float) -> dict:
    """
    Returns one raw telemetry dict, shaped exactly like what
    serial_bridge.py sends. `t` is elapsed seconds since start; the
    values below cycle through a ~24s pattern:

        0-6s   straight, cruising speed
        6-10s  curve entry / curve (lean + light braking)
        10-14s curve exit (throttle back on, lean returning to 0)
        14-20s straight / cruising again
        20-24s slowing to a stop
    """
    cycle = t % 24.0

    if cycle < 6:
        speed = 30 + 4 * math.sin(t / 2)
        accel = 0.05 * math.sin(t)
        roll = 0.02 * math.sin(t / 3)
    elif cycle < 10:
        speed = 24 - 2 * (cycle - 6)
        accel = -0.12
        roll = 0.55 * math.sin((cycle - 6) / 4 * math.pi)
    elif cycle < 14:
        speed = 20 + 3 * (cycle - 10)
        accel = 0.20
        roll = 0.35 * math.sin((cycle - 10) / 4 * math.pi + math.pi)
    elif cycle < 20:
        speed = 32 + 3 * math.sin(t / 2)
        accel = 0.04 * math.sin(t)
        roll = 0.03 * math.sin(t / 3)
    else:
        progress = (cycle - 20) / 4.0
        speed = max(0.0, 32 * (1 - progress))
        accel = -0.18
        roll = 0.0

    yaw = roll * 40  # rough coupling, good enough for test data

    return {
        "time": round(t, 3),
        "speed": round(max(0.0, speed), 2),
        "accel": round(accel, 4),
        "roll": round(roll, 4),
        "yaw": round(yaw, 3),
        "lat": 14.599512,
        "lon": 121.036192,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", default=DEFAULT_URL,
        help=f"telemetry endpoint to POST to (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--interval", type=float, default=SEND_INTERVAL,
        help=f"seconds between sends (default: {SEND_INTERVAL})",
    )
    args = parser.parse_args()

    print(f"Sending mock telemetry to {args.url} every {args.interval}s. "
          f"Press Ctrl+C to stop.\n")

    session = requests.Session()
    start = time.time()

    try:
        while True:
            t = time.time() - start
            sample = build_sample(t)
            try:
                resp = session.post(args.url, json=sample, timeout=5)
                print(f"\rt={t:6.1f}s  speed={sample['speed']:5.1f}  "
                      f"accel={sample['accel']:+.3f}  roll={sample['roll']:+.3f}  "
                      f"-> POST {resp.status_code}", end="", flush=True)
            except requests.exceptions.RequestException as exc:
                print(f"\rt={t:6.1f}s  POST FAILED: {exc}", end="", flush=True)

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\nStopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()