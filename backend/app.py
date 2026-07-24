"""
app.py
======
Flask backend for the motorcycle telemetry system.

--- JOB E ADDENDUM --------------------------------------------------------
The Arduino sketch now also POSTs a real "throttle" field (0-100), sourced
from a second, calibrated MPU6050 latched to the throttle tube. This file
only needed one line changed: pass payload["throttle"] through to
RawSample so feature_engineering.py can use the real value instead of its
old acceleration-based proxy. /latest's byte-exact JOB A contract is
unaffected either way - it already stores/returns the payload verbatim.
---------------------------------------------------------------------------
"""

import json
import logging
import time

import classifier  # --- JOB B
from feature_engineering import FeatureEngineer, RawSample  # --- JOB B
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("motorcycle-backend")

app = Flask(__name__)
CORS(app)

# --- JOB A: exactly what /latest returns. Never touched by JOB B. -----
latest_data: dict = {}

# --- JOB B: raw + derived + classification fields, for /stream only ---
latest_stream_data: dict = {}

_feature_engineer = FeatureEngineer()   # one bike per process today

KEEPALIVE_INTERVAL_S = 15


@app.route("/")
def health():
    return "Motorcycle Telemetry Backend Running"


@app.route("/debug/model-status")
def debug_model_status():
    return jsonify(classifier.status())


@app.route("/telemetry", methods=["POST"])
def telemetry():
    global latest_data, latest_stream_data

    payload = request.get_json(force=True, silent=True) or {}

    # --- JOB A behaviour, preserved byte-for-byte, never modified ------
    latest_data = dict(payload)

    # --- JOB B: derive the 5 model features + classify (fail-soft) ----
    stream_payload = dict(payload)
    try:
        raw = RawSample(
            time=float(payload.get("time", 0.0)),
            speed=float(payload.get("speed", 0.0)),
            accel_lon=float(payload.get("accel", 0.0)),
            roll=float(payload.get("roll", 0.0)),
            yaw_rate=float(payload.get("yaw", 0.0)),
            lat=float(payload.get("lat", 0.0)),
            lon=float(payload.get("lon", 0.0)),
            brake=(payload.get("brake") if "brake" in payload else None),
            throttle=(payload.get("throttle") if "throttle" in payload else None),  # --- JOB E
        )
        features = _feature_engineer.compute(raw)
        result = classifier.classify(
            acc_forward=features.acc_forward,
            lean_angle=features.lean_angle,
            lean_rate=features.lean_rate,
            throttle=features.throttle,
            brake=features.brake,
            speed=features.speed
        )
        stream_payload.update({
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
            "/latest is unaffected, /stream falls back to raw telemetry: %s",
            exc,
        )
        stream_payload.setdefault("riding_state", None)
        stream_payload.setdefault("riding_state_confidence", None)

    stream_payload["server_time"] = time.time()
    latest_stream_data = stream_payload

    return jsonify({"status": "received"}), 200


@app.route("/latest")
def latest():
    return jsonify(latest_data)


@app.route("/stream")
def stream():
    def event_stream():
        last_sent = None
        last_keepalive = time.time()
        while True:
            now = time.time()
            if latest_stream_data and latest_stream_data != last_sent:
                yield f"data: {json.dumps(latest_stream_data)}\n\n"
                last_sent = dict(latest_stream_data)
                last_keepalive = now
            elif now - last_keepalive > KEEPALIVE_INTERVAL_S:
                yield ": keepalive\n\n"
                last_keepalive = now
            time.sleep(0.1)

    return Response(event_stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)