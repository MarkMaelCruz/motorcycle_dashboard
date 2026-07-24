"""
feature_engineering.py
=======================
Single source of truth for turning RAW Arduino telemetry into the
5 features the riding-control classifier (lgbm_model_bundle.pkl)
expects.

--- JOB E ADDENDUM --------------------------------------------------------
A real throttle-position sensor now exists (a second MPU6050, latched to
the throttle tube, I2C address 0x68). The Arduino sketch calibrates and
smooths it on-device and emits it as a 0-100 "throttle" field, exactly the
same way "brake" has worked since the VL53L0X was added. RawSample now
carries an optional `throttle` field; when present it is used directly
(clamped to 0-100) instead of the old forward-acceleration proxy. The
proxy remains as a fallback for payloads that don't include it yet (e.g.
older firmware, or replaying old recorded logs).
---------------------------------------------------------------------------

WHY THIS FILE EXISTS
---------------------
The Arduino (raw .ino) only ever transmitted 7 raw fields historically:

    time, speed, accel_lon, roll, yaw_rate, lat, lon

- accel_lon  -> forward/backward acceleration in g (bias-corrected on the MCU)
- roll       -> NOT a lean angle in degrees. It is accY, the *lateral*
                acceleration in g (bias-corrected on the MCU). The CSV
                header calls this column "roll" but it is a raw
                g-force reading, which is why it (and everything
                downstream of it) showed near-zero on the live
                dashboard.
- yaw_rate   -> gyroscope Z-axis rate in deg/s (bias-corrected on the MCU)

The trained model expects:

    acc_forward, lean_angle, lean_rate, throttle, brake

lean_angle / lean_rate are DERIVED from the raw lateral-g reading.
brake and (as of JOB E) throttle now come from real, calibrated
on-device sensors (VL53L0X TOF and a second MPU6050, respectively) and
are passed straight through here rather than estimated.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger("feature_engineering")

# ---- Tunable constants -------------------------------------------------
MAX_LEAN_G = 1.0               # accY magnitude treated as ~90 deg lean (clamped)
MAX_THROTTLE_ACCEL_G = 0.70    # forward accel (g) mapped to 100% throttle proxy (fallback only)
MAX_BRAKE_ACCEL_G = 0.45       # forward decel (g) mapped to 100% brake proxy (fallback only)

# --- JOB D: plausibility-guard constants ---------------------------------
PLAUSIBLE_LEAN_G_CEILING = 0.85          # ~58 deg - beyond this, flag as suspect
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
    brake: float | None = None
    throttle: float | None = None   # --- JOB E: real throttle-position sensor


@dataclass
class DerivedFeatures:
    """Exactly the 5 columns the model bundle's feature_cols expects,
    plus an optional diagnostic flag that is NOT one of the 5 model
    features."""
    acc_forward: float
    lean_angle: float
    lean_rate: float
    throttle: float
    brake: float
    sensor_flag: str | None = None   # --- JOB D, diagnostic only


def _check_plausibility(raw: RawSample) -> str | None:
    """Flags (does not correct) readings consistent with a bad/stale
    accelerometer calibration rather than real rider input."""
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
    Keep ONE instance per logical bike/stream.
    """

    def __init__(self) -> None:
        self._prev_lean_angle: float | None = None
        self._prev_time: float | None = None

    def reset(self) -> None:
        self._prev_lean_angle = None
        self._prev_time = None

    def compute(self, raw: RawSample) -> DerivedFeatures:
        sensor_flag = _check_plausibility(raw)
        if sensor_flag:
            logger.warning("Implausible raw telemetry: %s", sensor_flag)

        # --- lean angle (deg) -------------------------------------------
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

        # --- brake percent: prefer real sensor value, fallback to proxy ---
        if raw.brake is not None:
            brake = _clamp(float(raw.brake), 0.0, 100.0)
        elif raw.accel_lon >= 0:
            brake = 0.0
        else:
            brake = _clamp(-raw.accel_lon / MAX_BRAKE_ACCEL_G, 0.0, 1.0) * 100.0

        # --- throttle percent: prefer real sensor value (JOB E), fallback to proxy ---
        if raw.throttle is not None:
            throttle = _clamp(float(raw.throttle), 0.0, 100.0)
        elif raw.accel_lon >= 0:
            throttle = _clamp(raw.accel_lon / MAX_THROTTLE_ACCEL_G, 0.0, 1.0) * 100.0
        else:
            throttle = 0.0

        return DerivedFeatures(
            acc_forward=raw.accel_lon,
            lean_angle=lean_angle,
            lean_rate=lean_rate,
            throttle=throttle,
            brake=brake,
            sensor_flag=sensor_flag,
        )