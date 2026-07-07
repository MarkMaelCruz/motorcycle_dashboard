from flask import Flask, request, jsonify
from flask_cors import CORS

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

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8080,
        debug=True
    )