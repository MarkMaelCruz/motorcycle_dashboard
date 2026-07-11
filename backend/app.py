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

>>> WHY /latest AND /stream NOW RETURN DIFFERENT SHAPES <<<
--------------------------------------------------------------
The real, existing JOB A test (backend/tests/test_app.py,
test_telemetry_then_latest) asserts:

    latest_response = client.get("/latest")
    assert latest_response.get_json() == payload

That is a STRICT equality check against exactly what was POSTed to
/telemetry — no extra keys allowed, ever. Two earlier attempts at this
file broke that contract in different ways:
  1. rebuilding /latest from a hardcoded field-name list (dropped
     lat/lon for real payloads that didn't match the guess), then
  2. merging the JOB B derived + classification fields directly into
     /latest (technically preserved the raw fields, but added new
     keys, which strict equality still rejects).

The fix: /latest now stores and returns the POSTed payload completely
untouched — JOB B never touches it. All of the new derived fields
(acc_forward, lean_angle, lean_rate, throttle, brake, riding_state,
riding_state_confidence) instead live ONLY in a second in-memory
value that backs /stream, which is what rider_dashboard.html actually
consumes via EventSource. JOB A's own test suite deliberately avoids
asserting on /stream's body (see the original CI job description:
"a /stream header/status check that deliberately avoids reading the
response body"), so /stream is the correct, safe place for this to
evolve without risking another regression here.

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
    """Diagnostic endpoint added to find exactly why riding_state was
    showing as null in production. Safe to leave in permanently (no
    secrets returned), or remove once the root cause is confirmed —
    see README.md for the removal note."""
    return jsonify(classifier.status())


@app.route("/telemetry", methods=["POST"])
def telemetry():
    global latest_data, latest_stream_data

    payload = request.get_json(force=True, silent=True) or {}

    # --- JOB A behaviour, preserved byte-for-byte, never modified ------
    # latest_data is returned verbatim by GET /latest. JOB B must never
    # add, remove, or rename a single key here.
    latest_data = dict(payload)

    # --- JOB B: derive the 5 model features + classify (fail-soft) ----
    # This builds a SEPARATE dict for /stream only. Wrapped in
    # try/except on purpose: if anything here throws (bad payload
    # shape, model not deployed yet, a math edge case), /latest above
    # is already safely stored, and /stream just falls back to raw
    # telemetry with riding_state: None instead of crashing the request.
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
        )
        features = _feature_engineer.compute(raw)
        result = classifier.classify(
            acc_forward=features.acc_forward,
            lean_angle=features.lean_angle,
            lean_rate=features.lean_rate,
            throttle=features.throttle,
            brake=features.brake,
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
    """Byte-exact echo of the last POSTed payload. JOB A contract — do
    not add fields here; add them to latest_stream_data / /stream
    instead."""
    return jsonify(latest_data)


@app.route("/stream")
def stream():
    """Server-Sent Events endpoint, Cloud Run compatible. Carries raw
    telemetry PLUS the JOB B derived + classification fields — this is
    what rider_dashboard.html's EventSource actually listens to."""

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