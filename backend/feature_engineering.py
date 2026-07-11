"""
feature_engineering.py
=======================
Single source of truth for turning RAW Arduino telemetry into the
5 features the riding-control classifier (lgbm_model_bundle.pkl)
expects.

WHY THIS FILE EXISTS
---------------------
The Arduino (raw .ino) only ever transmits 7 raw fields:

    time, speed, accel_lon, roll, yaw_rate, lat, lon

- accel_lon  -> forward/backward acceleration in g (bias-corrected on the MCU)
- roll       -> NOT a lean angle in degrees. It is accY, the *lateral*
                acceleration in g (bias-corrected on the MCU). The CSV
                header calls this column "roll" but it is a raw
                g-force reading, which is why it (and everything
                downstream of it) showed near-zero on the live
                dashboard.
- yaw_rate   -> gyroscope Z-axis rate in deg/s (bias-corrected on the MCU)

The trained model, however, expects:

    acc_forward, lean_angle, lean_rate, throttle, brake

None of those 5 columns exist on the hardware today:
  * lean_angle / lean_rate must be DERIVED from the raw lateral-g reading.
  * throttle / brake sensors do not physically exist on the bike yet
    (see project docs, "Future sensors"). Their values are ESTIMATED
    (proxied) from forward acceleration: positive accel behaves like
    throttle, negative accel behaves like braking.

This is exactly why raspberry_pi/serial_bridge.py (which only forwards
raw values) looked "dead" online while rider_control_classification.py
(which computed these derived features locally before calling the
model) looked "alive". This module centralises that derivation so the
SAME logic runs in exactly one place going forward: the Cloud Run
backend, on every POST /telemetry.

--- JOB D ADDENDUM -------------------------------------------------------
A separate bug (fixed at the source, in the .ino's calibration timing -
see Project Context Handoff, JOB D) previously caused "bias-corrected"
raw values to carry a large, sustained, physically implausible offset
(e.g. sustained ~0.44g accel_lon and ~1.11g roll while the bike sat
completely still). That is NOT sensor noise and a noise deadzone would
not have fixed it - the offset was tightly banded around a wrong
non-zero value, not jittering around zero. The real fix lives on the
Arduino: calibration now waits for the device to be physically stable
before it locks in "zero", and can be re-triggered on demand.

This file adds a belt-and-suspenders defensive check ONLY: if a raw
reading is ever physically implausible for a motorcycle at rest/normal
riding (e.g. sustained lateral g near the +-1.0g clamp ceiling, which
would mean gravity is being read as fully sideways), it's flagged
rather than silently reported as a confident 90-degree lean or 100%
throttle. This does not attempt to correct a miscalibration in
software - see the .ino fix for that - it only stops a miscalibration
from masquerading as normal telemetry.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("feature_engineering")

# ---- Tunable constants -------------------------------------------------
# Starting points based on the sensor's g-range and values observed
# during the first test rides (rider_control_classification.py).
# Retune once real throttle/brake sensors land (see project roadmap).

MAX_LEAN_G = 1.0               # accY magnitude treated as ~90 deg lean (clamped)
MAX_THROTTLE_ACCEL_G = 0.35    # forward accel (g) mapped to 100% throttle proxy
MAX_BRAKE_ACCEL_G = 0.45       # forward decel (g) mapped to 100% brake proxy

# --- JOB D: plausibility-guard constants ---------------------------------
# A real motorcycle at normal riding lean rarely exceeds ~45 deg
# (~0.7g lateral); a value this close to the 1.0g clamp ceiling for a
# SUSTAINED period (not a single noisy tick) is far more likely to be
# a bad calibration offset than a real, physically extreme lean.
PLAUSIBLE_LEAN_G_CEILING = 0.85          # ~58 deg - beyond this, flag as suspect
# A held forward/back accel this large for a sustained period while
# GPS speed is not changing accordingly is a strong bias-offset signal
# (this is exactly the pattern that surfaced the JOB D bug: ~0.44g
# held for 5+ seconds with speed locked at 6.26 km/h the whole time).
PLAUSIBLE_ACCEL_G_CEILING = 0.6
STATIONARY_SPEED_KMPH = 1.0              # GPS speed below this = "not really moving"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass
class RawSample:
    """Exactly the fields raspberry_pi/serial_bridge.py already POSTs."""
    time: float
    speed: float
    accel_lon: float   # g, forward/back  (posted as "accel")
    roll: float          # g, lateral (posted as "roll" - NOT degrees)
    yaw_rate: float       # deg/s          (posted as "yaw")
    lat: float = 0.0
    lon: float = 0.0


@dataclass
class DerivedFeatures:
    """Exactly the 5 columns the model bundle's feature_cols expects,
    plus an optional diagnostic flag that is NOT one of the 5 model
    features (see classifier.classify(), which only ever reads the
    5 named args) and is safe for app.py to include in
    latest_stream_data or ignore entirely without affecting JOB A's
    /latest contract."""
    acc_forward: float
    lean_angle: float
    lean_rate: float
    throttle: float
    brake: float
    sensor_flag: Optional[str] = None   # --- JOB D, diagnostic only


def _check_plausibility(raw: RawSample) -> Optional[str]:
    """Flags (does not correct) readings consistent with a bad/stale
    accelerometer calibration rather than real rider input. See the
    JOB D module docstring for the reasoning."""
    if abs(raw.roll) >= PLAUSIBLE_LEAN_G_CEILING:
        return (
            f"roll={raw.roll:.3f}g exceeds plausible lean ceiling "
            f"({PLAUSIBLE_LEAN_G_CEILING}g) - possible miscalibration"
        )
    if (
        abs(raw.accel_lon) >= PLAUSIBLE_ACCEL_G_CEILING
        and raw.speed < STATIONARY_SPEED_KMPH
    ):
        return (
            f"accel_lon={raw.accel_lon:.3f}g while speed={raw.speed:.2f}km/h "
            f"(near-stationary) - possible miscalibration"
        )
    return None


class FeatureEngineer:
    """
    Stateful because lean_rate needs the previous lean_angle + dt.

    Keep ONE instance per logical bike/stream. The default backend
    integration keeps a single process-wide instance because the
    system currently tracks one active bike (see project docs,
    "multi-session analytics" is a future feature).
    """

    def __init__(self) -> None:
        self._prev_lean_angle: Optional[float] = None
        self._prev_time: Optional[float] = None

    def reset(self) -> None:
        self._prev_lean_angle = None
        self._prev_time = None

    def compute(self, raw: RawSample) -> DerivedFeatures:
        # --- JOB D: plausibility guard (diagnostic only, no correction) --
        sensor_flag = _check_plausibility(raw)
        if sensor_flag:
            logger.warning("Implausible raw telemetry: %s", sensor_flag)

        # --- lean angle (deg) -------------------------------------------
        # accY (raw.roll) is lateral g. With gravity ~1g on the vertical
        # axis at rest, lean angle ~= asin(lateral_g / 1g). The ratio is
        # clamped to [-1, 1] before asin() to survive noisy ticks.
        ratio = _clamp(raw.roll / MAX_LEAN_G, -1.0, 1.0)
        lean_angle = math.degrees(math.asin(ratio))

        # --- lean rate (deg/s) -------------------------------------------
        if self._prev_lean_angle is not None and self._prev_time is not None:
            dt = raw.time - self._prev_time
            lean_rate = (lean_angle - self._prev_lean_angle) / dt if dt > 1e-3 else 0.0
        else:
            lean_rate = 0.0

        self._prev_lean_angle = lean_angle
        self._prev_time = raw.time

        # --- throttle / brake proxies (percent, 0-100) --------------------
        # No physical throttle/brake sensor exists yet, so these are
        # estimated purely from forward/back acceleration.
        if raw.accel_lon >= 0:
            throttle = _clamp(raw.accel_lon / MAX_THROTTLE_ACCEL_G, 0.0, 1.0) * 100.0
            brake = 0.0
        else:
            throttle = 0.0
            brake = _clamp(-raw.accel_lon / MAX_BRAKE_ACCEL_G, 0.0, 1.0) * 100.0

        return DerivedFeatures(
            acc_forward=raw.accel_lon,
            lean_angle=lean_angle,
            lean_rate=lean_rate,
            throttle=throttle,
            brake=brake,
            sensor_flag=sensor_flag,
        )
