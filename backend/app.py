from flask import Flask, request, jsonify, Response
from flask_cors import CORS

import json
import time

app = Flask(__name__)
CORS(app)

latest_data = {}


@app.route("/")
def home():
    return "Motorcycle Telemetry Backend Running"


@app.route("/telemetry", methods=["POST"])
def telemetry():

    global latest_data

    latest_data = request.json

    return jsonify({
        "status": "received"
    })


@app.route("/latest")
def latest():

    return jsonify(latest_data)


@app.route("/stream")
def stream():

    def event_stream():

        last_payload = ""

        while True:

            try:

                payload = json.dumps(latest_data)

                if payload != last_payload:

                    yield f"data: {payload}\n\n"

                    last_payload = payload

                else:

                    yield ": keepalive\n\n"

                time.sleep(1)

            except GeneratorExit:

                break

            except Exception as e:

                print("STREAM ERROR:", e)

                break

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=True
    )