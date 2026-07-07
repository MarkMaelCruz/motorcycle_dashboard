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

            global latest_data

            payload = json.dumps(
                latest_data
            )

            if payload != last_payload:

                yield f"data: {payload}\n\n"

                last_payload = payload

            time.sleep(0.02)

    return Response(
        event_stream(),
        mimetype="text/event-stream"
    )


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=True
    )