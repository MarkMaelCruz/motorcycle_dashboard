import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import app as app_module
from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as test_client:
        yield test_client


def test_health_check(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Motorcycle Telemetry Backend Running" in response.data


def test_telemetry_then_latest(client):
    payload = {
        "time": 12.52,
        "speed": 25.6,
        "accel": -0.042,
        "roll": 3.2,
        "yaw": 1.1,
        "lat": 14.599512,
        "lon": 121.036192,
    }

    post_response = client.post("/telemetry", json=payload)
    assert post_response.status_code == 200
    assert post_response.get_json() == {"status": "received"}

    latest_response = client.get("/latest")
    assert latest_response.status_code == 200
    assert latest_response.get_json() == payload


def test_stream_endpoint_is_sse(client):
    # Only check headers/status here. The generator behind /stream runs
    # an infinite loop by design (it's a live feed) — reading its body
    # in a test would hang the test run forever, so we never touch
    # response.data on this one.
    response = client.get("/stream")
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    response.close()


def test_telemetry_uses_incoming_brake_value(client):
    payload = {
        "time": 12.52,
        "speed": 25.6,
        "accel": -0.042,
        "roll": 3.2,
        "yaw": 1.1,
        "lat": 14.599512,
        "lon": 121.036192,
        "brake": 67.5,
    }

    response = client.post("/telemetry", json=payload)
    assert response.status_code == 200

    latest_stream = app_module.latest_stream_data
    assert latest_stream["brake"] == 67.5
