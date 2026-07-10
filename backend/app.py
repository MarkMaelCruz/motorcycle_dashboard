"""
app.py
======
Flask backend for the motorcycle telemetry system.

>>> IMPORTANT NOTE ON THIS FILE <<<
------------------------------------
The project docs describe this file's existing behaviour (GET /,
POST /telemetry, GET /latest, GET /stream with SSE + keepalive, CORS
enabled, served by Gunicorn on Cloud Run) but the actual current
source of backend/app.py was not included in the files provided for
this change. This file has therefore been RECONSTRUCTED to match that
documented behaviour, with the new JOB B classification step layered
on top (see comments tagged "# --- JOB B").

An earlier version of this reconstruction rebuilt the /latest response
from a hardcoded list of field names ("time", "speed", "accel", "roll",
"yaw", "lat", "lon"). That caused the existing JOB A test
(test_telemetry_then_latest) to fail with "lat"/"lon" missing from the
response, because it silently assumed a payload shape that didn't
exactly match reality. POST /telemetry now instead stores the incoming
JSON payload VERBATIM and only ADDS the new JOB B fields on top — it
never renames or reconstructs anything — so nothing that worked before
this change can regress, no matter the exact real payload shape.

BEFORE DEPLOYING: diff this against your real backend/app.py and port
the JOB B blocks into your existing file instead of blindly
overwriting anything else you have already customised there.
"""

import time
import json
import logging

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

from feature_engineering import FeatureEngineer, RawSample   # --- JOB B
import classifier                                              # --- JOB B

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("motorcycle-backend")

app = Flask(__name__)
CORS(app)

latest_data: dict = {}
_feature_engineer = FeatureEngineer()   # --- JOB B (one bike per process today)

KEEPALIVE_INTERVAL_S = 15


@app.route("/")
def health():
    return "Motorcycle Telemetry Backend Running"


@app.route("/telemetry", methods=["POST"])
def telemetry():
    global latest_data

    payload = request.get_json(force=True, silent=True) or {}

    # --- JOB A behaviour, preserved byte-for-byte ---------------------
    # Start from EXACTLY what was received. This guarantees every field
    # the Pi sends (time, speed, accel, roll, yaw, lat, lon, or anything
    # else) round-trips through GET /latest unchanged, regardless of
    # what JOB B does below. This is what was previously broken: an
    # earlier version of this file rebuilt the response from a
    # hardcoded list of field names instead of passing the payload
    # through, which silently dropped "lat"/"lon" for anyone whose
    # real payload shape didn't match that hardcoded guess exactly.
    merged = dict(payload)

    # --- JOB B: derive the 5 model features + classify (fail-soft) ----
    # Wrapped in try/except on purpose: if anything here throws (bad
    # payload shape, model not deployed yet, a math edge case), the
    # raw telemetry above must still be stored and returned. JOB B is
    # additive only — it must never be able to take down /telemetry.
    try:
        raw = RawSample(
            time=float(payload.get("time", 0.0)),
            speed=float(payload.get("speed", 0.0)),
            accel_lon=float(payload.get("accel", 0.0)),
            roll=float(payload.get("roll", 0.0)),
            yaw_rate=float(payload.get("yaw", 0.0)),
            lat=float(payload.get("lat", 0.0)),
            lon=float(payload.get("lon", 0.0)),
        )
        features = _feature_engineer.compute(raw)
        result = classifier.classify(
            acc_forward=features.acc_forward,
            lean_angle=features.lean_angle,
            lean_rate=features.lean_rate,
            throttle=features.throttle,
            brake=features.brake,
        )
        merged.update({
            "acc_forward": features.acc_forward,
            "lean_angle": features.lean_angle,
            "lean_rate": features.lean_rate,
            "throttle": features.throttle,
            "brake": features.brake,
            "riding_state": result["label"] if result else None,
            "riding_state_confidence": result["confidence"] if result else None,
        })
    except Exception as exc:  # noqa: BLE001 - JOB B must fail soft, always
        logger.warning(
            "JOB B feature engineering / classification step failed; "
            "raw telemetry was still stored unchanged: %s", exc
        )
        merged.setdefault("riding_state", None)
        merged.setdefault("riding_state_confidence", None)

    merged["server_time"] = time.time()
    latest_data = merged

    return jsonify({"status": "ok"}), 200


@app.route("/latest")
def latest():
    return jsonify(latest_data)


@app.route("/stream")
def stream():
    """Server-Sent Events endpoint, Cloud Run compatible."""

    def event_stream():
        last_sent = None
        last_keepalive = time.time()
        while True:
            now = time.time()
            if latest_data and latest_data != last_sent:
                yield f"data: {json.dumps(latest_data)}\n\n"
                last_sent = dict(latest_data)
                last_keepalive = now
            elif now - last_keepalive > KEEPALIVE_INTERVAL_S:
                yield ": keepalive\n\n"
                last_keepalive = now
            time.sleep(0.1)

    return Response(event_stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)