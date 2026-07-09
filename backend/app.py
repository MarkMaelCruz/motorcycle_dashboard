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
documented behaviour exactly, with the new JOB B classification step
layered on top (see comments tagged "# --- JOB B").
 
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
 
    # Raw fields exactly as sent today by raspberry_pi/serial_bridge.py
    raw = RawSample(
        time=float(payload.get("time", 0.0)),
        speed=float(payload.get("speed", 0.0)),
        accel_lon=float(payload.get("accel", 0.0)),
        roll=float(payload.get("roll", 0.0)),
        yaw_rate=float(payload.get("yaw", 0.0)),
        lat=float(payload.get("lat", 0.0)),
        lon=float(payload.get("lon", 0.0)),
    )
 
    # --- JOB B: derive the 5 model features + classify the riding state ---
    features = _feature_engineer.compute(raw)
    result = classifier.classify(
        acc_forward=features.acc_forward,
        lean_angle=features.lean_angle,
        lean_rate=features.lean_rate,
        throttle=features.throttle,
        brake=features.brake,
    )
 
    latest_data = {
        # --- raw passthrough, unchanged field names (JOB A behaviour) ---
        "time": raw.time,
        "speed": raw.speed,
        "accel": raw.accel_lon,
        "roll": raw.roll,
        "yaw": raw.yaw_rate,
        "lat": raw.lat,
        "lon": raw.lon,
        # --- JOB B: additive fields only, nothing above was removed ---
        "acc_forward": features.acc_forward,
        "lean_angle": features.lean_angle,
        "lean_rate": features.lean_rate,
        "throttle": features.throttle,
        "brake": features.brake,
        "riding_state": result["label"] if result else None,
        "riding_state_confidence": result["confidence"] if result else None,
        "server_time": time.time(),
    }
 
    return jsonify({"status": "received"}), 200
 
 
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
 